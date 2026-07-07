from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AccessAidServer")

@mcp.tool()
def simplify_text_vocabulary(text: str) -> str:
    """Simplifies typical complex, technical, or high-level vocabulary in document text for cognitive accessibility."""
    replacements = {
        "utilize": "use",
        "facilitate": "help",
        "consequently": "so",
        "subsequent": "next",
        "termination": "end",
        "aggregate": "total",
        "corroborate": "confirm",
        "disseminate": "spread",
        "elucidate": "explain",
        "implement": "carry out",
        "erroneous": "wrong",
        "expeditious": "quick"
    }
    words = text.split()
    simplified_words = []
    for word in words:
        clean_word = word.strip(".,;:?!\"'()").lower()
        if clean_word in replacements:
            replaced = replacements[clean_word]
            if word[0].isupper():
                replaced = replaced.capitalize()
            prefix = ""
            suffix = ""
            if word.endswith((".", ",", ";", ":", "?", "!")):
                suffix = word[-1]
            simplified_words.append(prefix + replaced + suffix)
        else:
            simplified_words.append(word)
    return " ".join(simplified_words)

@mcp.tool()
def check_contrast_ratio(foreground_hex: str, background_hex: str) -> str:
    """Calculates the WCAG contrast ratio for foreground and background colors to verify visual accessibility. Colors must be hex format (e.g. #FFFFFF or #000000)."""
    def parse_hex(hex_str):
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 3:
            hex_str = ''.join([c*2 for c in hex_str])
        return [int(hex_str[i:i+2], 16) for i in (0, 2, 4)]

    def get_luminance(r, g, b):
        parts = []
        for c in (r, g, b):
            c_s = c / 255.0
            if c_s <= 0.04045:
                parts.append(c_s / 12.92)
            else:
                parts.append(((c_s + 0.055) / 1.055) ** 2.4)
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    try:
        rgb1 = parse_hex(foreground_hex)
        rgb2 = parse_hex(background_hex)
    except Exception as e:
        return f"Error parsing hex colors: {e}. Please provide colors in valid hex format."

    lum1 = get_luminance(*rgb1)
    lum2 = get_luminance(*rgb2)

    l1 = max(lum1, lum2)
    l2 = min(lum1, lum2)

    ratio = (l1 + 0.05) / (l2 + 0.05)
    
    status = f"Contrast Ratio: {ratio:.2f}:1\n"
    if ratio >= 7.0:
        status += "Passes WCAG AAA for all text formats."
    elif ratio >= 4.5:
        status += "Passes WCAG AA for all text formats; passes WCAG AAA for large text."
    elif ratio >= 3.0:
        status += "Passes WCAG AA for large text; fails WCAG AA for normal text."
    else:
        status += "Fails WCAG AA. Visual accessibility adjustment required."
    return status

@mcp.tool()
def format_screen_reader_table(table_data_str: str) -> str:
    """Converts a standard Markdown table format string into a linear, screen-reader friendly narrative text description."""
    lines = [line.strip() for line in table_data_str.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        return "Empty or invalid table data."

    header_line = lines[0]
    headers = [h.strip() for h in header_line.split('|') if h.strip()]
    
    start_idx = 1
    if len(lines) > 1 and all(c in '|- ' for c in lines[1]):
        start_idx = 2

    narrative = []
    row_count = 1
    for i in range(start_idx, len(lines)):
        row_line = lines[i]
        cells = [c.strip() for c in row_line.split('|') if c.strip()]
        if not cells:
            continue
        row_desc = f"Row {row_count}: "
        cell_descs = []
        for h_idx, cell in enumerate(cells):
            header = headers[h_idx] if h_idx < len(headers) else f"Column {h_idx+1}"
            cell_descs.append(f"{header} is {cell}")
        row_desc += ", ".join(cell_descs) + "."
        narrative.append(row_desc)
        row_count += 1

    return f"This table contains {row_count-1} rows. Here is the screen-reader narration:\n" + "\n".join(narrative)

if __name__ == "__main__":
    mcp.run()
