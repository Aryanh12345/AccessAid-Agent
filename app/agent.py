# ruff: noqa
import re
import json
import logging
import datetime
import os
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool, McpToolset
from google.adk.workflow import node, START, Workflow
from google.adk import Context
from mcp import StdioServerParameters

from .config import config

# ─── Logging ──────────────────────────────────────────────────────────────────
audit_logger = logging.getLogger("accessaid.audit")
audit_logger.setLevel(logging.DEBUG)
if not audit_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(_h)


def _audit(severity: str, event: str, detail: str = "", ctx_state = None) -> None:
    """Emit a structured JSON audit log entry."""
    state_keys = []
    if ctx_state:
        if hasattr(ctx_state, "to_dict"):
            state_keys = list(ctx_state.to_dict().keys())
        elif hasattr(ctx_state, "keys"):
            state_keys = list(ctx_state.keys())
            
    record = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "severity": severity,          # INFO | WARNING | CRITICAL
        "event": event,
        "detail": detail,
        "state_keys": state_keys,
    }
    audit_logger.info(json.dumps(record))


# ─── PII Scrubbing ─────────────────────────────────────────────────────────────
_PII_PATTERNS = [
    # Email addresses
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL]"),
    # Phone numbers (various formats)
    (re.compile(r"\b(?:\+?\d{1,3}[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"), "[PHONE]"),
    # Social Security Numbers
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    # Credit card numbers (basic pattern)
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
    # National IDs / Aadhaar-like (12 digit)
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[NATIONAL_ID]"),
    # Dates of birth (e.g. 01/01/1990)
    (re.compile(r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b"), "[DOB]"),
    # IP addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
]


def _scrub_pii(text: str) -> tuple[str, list[str]]:
    """Scrub PII from text. Returns (clean_text, list_of_redactions)."""
    redactions = []
    for pattern, replacement in _PII_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            redactions.append(f"{replacement}: {len(matches)} occurrence(s)")
            text = pattern.sub(replacement, text)
    return text, redactions


# ─── Prompt Injection Detection ────────────────────────────────────────────────
_INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "disregard all",
    "forget your instructions",
    "you are now",
    "act as",
    "jailbreak",
    "bypass",
    "override prompt",
    "system prompt",
    "new persona",
    "pretend you are",
    "roleplay as",
    "sudo",
    "execute command",
    "run script",
]


def _detect_injection(text: str) -> bool:
    """Return True if any injection keyword is found (case-insensitive)."""
    lower = text.lower()
    return any(kw in lower for kw in _INJECTION_KEYWORDS)


# ─── Domain-specific rule: Accessibility content consent check ─────────────────
_MIN_CONTENT_WORDS = 5
_MAX_CONTENT_CHARS = 50_000


def _check_content_policy(text: str) -> tuple[bool, str]:
    """Enforce AccessAid-specific content rules.
    Returns (passed, reason).
    """
    word_count = len(text.split())
    if word_count < _MIN_CONTENT_WORDS:
        return False, f"Content too short ({word_count} words). Provide at least {_MIN_CONTENT_WORDS} words."
    if len(text) > _MAX_CONTENT_CHARS:
        return False, f"Content exceeds {_MAX_CONTENT_CHARS} characters. Please split it into smaller sections."
    return True, "OK"


# ─── Initialize models ─────────────────────────────────────────────────────────
gemini_model = Gemini(model=config.model)

# ─── MCP Toolset ───────────────────────────────────────────────────────────────
mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "app.mcp_server"]
    )
)

# ─── Sub-agents ────────────────────────────────────────────────────────────────
document_analyzer_agent = LlmAgent(
    name="document_analyzer_agent",
    description="Analyzes input document format, layout, headers, links, and forms to suggest accessibility formatting.",
    model=gemini_model,
    instruction="""You are a Document Analyzer Agent.
Analyze structure of the input content (text layout, headers, form fields, images/links) and list specific formatting recommendations for screen readers, high-contrast, and simplified cognitive structures.
Do not summarize yet; focus on formatting and layout details.

You have access to tools:
- check_contrast_ratio: Checks contrast ratios for visual accessibility.
- simplify_text_vocabulary: Simplifies jargon.
Use these tools when appropriate during analysis.
""",
    tools=[mcp_toolset]
)

accessibility_summarizer_agent = LlmAgent(
    name="accessibility_summarizer_agent",
    description="Generates an accessible, simplified, screen-reader friendly summary of content based on layout guidance.",
    model=gemini_model,
    instruction="""You are an Accessibility Summarizer Agent.
Take raw content and structure recommendations and produce a screen-reader friendly summary.
Format headings clearly, add high-contrast text descriptions for any visual components, explain form fields step-by-step, and simplify complex words.

You have access to tools:
- format_screen_reader_table: Narrates tables for screen readers.
- simplify_text_vocabulary: Simplifies difficult words.
Use these tools when appropriate during generation.
""",
    tools=[mcp_toolset]
)

# ─── Orchestrator agent ────────────────────────────────────────────────────────
orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    description="Coordinates specialized sub-agents to analyze and format document for accessibility.",
    model=gemini_model,
    instruction="""You are the main coordinator for AccessAid.
You take a document/webpage input. Delegate analysis to document_analyzer_agent and summarization to accessibility_summarizer_agent.
Combine their results into a final accessible report that lists:
1. Document Structure & Reading Path
2. Simplified Accessible Summary
3. Screen-Reader friendly instructions
""",
    tools=[
        AgentTool(agent=document_analyzer_agent),
        AgentTool(agent=accessibility_summarizer_agent)
    ]
)


# ─── Workflow nodes ────────────────────────────────────────────────────────────

@node
async def security_checkpoint(ctx: Context, node_input: str):
    """
    PHASE 4 Security Checkpoint.

    Stage logic (via ctx.state['workflow_stage']):
      'new'              → run full security checks → SAFE or BLOCKED
      'awaiting_approval'→ user is replying 'approve'/'reject' → AWAITING
      'regenerate'       → human rejected, re-run orchestrator → SAFE
    """
    stage = ctx.state.get("workflow_stage", "new")

    # ── Resume path: waiting for human approval ───────────────────────────────
    if stage == "awaiting_approval":
        _audit(
            severity="INFO",
            event="SECURITY_CHECKPOINT_RESUME",
            detail=f"Stage=awaiting_approval. User reply: '{node_input[:30]}'",
            ctx_state=ctx.state,
        )
        ctx.state["human_decision"] = node_input.strip().lower()
        ctx.route = "AWAITING"
        return "AWAITING"

    # ── Re-generate path: human rejected ─────────────────────────────────────
    if stage == "regenerate":
        _audit(
            severity="INFO",
            event="SECURITY_CHECKPOINT_REGENERATE",
            detail="Human rejected report. Re-running orchestrator.",
            ctx_state=ctx.state,
        )
        ctx.state["workflow_stage"] = "new"
        ctx.route = "SAFE"
        return "SAFE"

    # ── First-pass path: brand new document input ─────────────────────────────
    # 1. PII Scrubbing
    clean_input, redactions = _scrub_pii(node_input)
    if redactions:
        _audit(
            severity="WARNING",
            event="PII_REDACTED",
            detail="; ".join(redactions),
            ctx_state=ctx.state,
        )

    # 2. Prompt Injection Detection
    if config.injection_detection_enabled and _detect_injection(clean_input):
        _audit(
            severity="CRITICAL",
            event="INJECTION_DETECTED",
            detail="Blocked: prompt injection keywords found in input.",
            ctx_state=ctx.state,
        )
        ctx.route = "BLOCKED"
        return "BLOCKED"

    # 3. Domain-specific content length rule
    passed, reason = _check_content_policy(clean_input)
    if not passed:
        _audit(
            severity="WARNING",
            event="CONTENT_POLICY_VIOLATION",
            detail=reason,
            ctx_state=ctx.state,
        )
        ctx.route = "BLOCKED"
        return "BLOCKED"

    # 4. All checks passed
    ctx.state["raw_input"] = clean_input
    ctx.state["pii_redacted"] = bool(redactions)
    ctx.state["workflow_stage"] = "new"
    _audit(
        severity="INFO",
        event="SECURITY_CHECKPOINT_PASSED",
        detail=f"PII redacted: {bool(redactions)}. Input length: {len(clean_input)} chars.",
        ctx_state=ctx.state,
    )
    ctx.route = "SAFE"
    return "SAFE"


@node
async def security_violation_node(ctx: Context, node_input: str):
    _audit(
        severity="CRITICAL",
        event="REQUEST_BLOCKED",
        detail="Input blocked at security checkpoint. Not forwarded to agents.",
        ctx_state=ctx.state,
    )
    return (
        "⛔ AccessAid Security: Your request was blocked.\n"
        "Reason: It contained sensitive personal data or disallowed instructions.\n"
        "Please resubmit with the document content only."
    )


@node(rerun_on_resume=True)
async def orchestrator_node(ctx: Context, node_input: str):
    raw_input = ctx.state.get("raw_input", node_input)
    result = await ctx.run_node(orchestrator_agent, node_input=raw_input)
    ctx.state["accessibility_report"] = result
    ctx.state["workflow_stage"] = "awaiting_approval"
    _audit(
        severity="INFO",
        event="ORCHESTRATOR_COMPLETE",
        detail=f"Report generated. Length: {len(str(result))} chars.",
        ctx_state=ctx.state,
    )
    return result


@node
async def human_approval_node(ctx: Context, node_input: str):
    """Shows the accessibility report and prompts the human for approval."""
    report = ctx.state.get("accessibility_report", node_input)
    _audit(
        severity="INFO",
        event="HITL_PAUSE",
        detail="Awaiting human verification of accessibility report.",
        ctx_state=ctx.state,
    )
    return (
        f"--- ✋ Human Verification Required ---\n"
        f"AccessAid has generated an accessibility report.\n\n"
        f"{report}\n\n"
        "──────────────────────────────────────────────────\n"
        "✅ Type  approve  to finalize and deliver the report.\n"
        "🔄 Type  reject   to regenerate with improvements."
    )


@node
async def human_decision_node(ctx: Context, node_input: str):
    """Reads 'approve'/'reject' from ctx.state (set by security_checkpoint on resume)."""
    decision = ctx.state.get("human_decision", "").strip().lower()
    _audit(
        severity="INFO",
        event="HITL_DECISION",
        detail=f"Human decision: '{decision}'",
        ctx_state=ctx.state,
    )
    if decision == "approve":
        ctx.route = "approved"
        return "approved"
    else:
        ctx.state["workflow_stage"] = "regenerate"
        ctx.route = "rejected"
        return "rejected"


@node
async def final_output_node(ctx: Context, node_input: str):
    report = ctx.state.get("accessibility_report", "No report generated.")
    pii_note = " (PII was detected and redacted from your input.)" if ctx.state.get("pii_redacted") else ""
    _audit(
        severity="INFO",
        event="FINAL_OUTPUT_DELIVERED",
        detail="Accessibility report delivered to user." + pii_note,
        ctx_state=ctx.state,
    )
    return f"--- ✅ AccessAid Final Accessible Output ---{pii_note}\n\n{report}"


# ─── Workflow graph ────────────────────────────────────────────────────────────
accessaid_workflow = Workflow(
    name="accessaid_workflow",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {
            "SAFE":     orchestrator_node,
            "AWAITING": human_decision_node,
            "BLOCKED":  security_violation_node,
        }),
        (orchestrator_node, human_approval_node),
        (human_decision_node, {"approved": final_output_node, "rejected": orchestrator_node}),
    ]
)

root_agent = accessaid_workflow

app = App(
    root_agent=root_agent,
    name="app",
)
