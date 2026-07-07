with open(r"c:\Users\DELL\Desktop\adk-workplace1\accessaid-agent\.venv\Lib\site-packages\google\adk\workflow\_workflow.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "def _run" in line or "def run" in line or "def _execute" in line:
        print(f"Line {idx+1}: {line.strip()}")
