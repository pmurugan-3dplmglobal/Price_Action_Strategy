import re, subprocess, tempfile, os, sys

def check_html_js(filepath):
    print(f"\nChecking HTML/JS in {filepath}...")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all <script> blocks (excluding external src)
    script_blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', content, re.DOTALL)
    print(f"Found {len(script_blocks)} inline script block(s).")

    for idx, code in enumerate(script_blocks, 1):
        # Replace Jinja placeholders {{ ... }} with dummy JS value
        clean_code = re.sub(r'\{\{.*?\}\}', '1000', code)
        clean_code = re.sub(r'\{%.*?%\}', '', clean_code)

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(clean_code)
            tmp_path = tmp.name

        try:
            res = subprocess.run(["node", "--check", tmp_path], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[SYNTAX ERROR] Script block {idx} failed syntax check:")
                print(res.stderr)
            else:
                print(f"[OK] Script block {idx} passed syntax check.")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    check_html_js("Trade_Stock/app_Stock_Trade.py")
    check_html_js("Trade_Option/app_option_Trade.py")
