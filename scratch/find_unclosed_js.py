import re, subprocess, tempfile, os

def find_script_lines():
    with open("Trade_Stock/app_Sock_Trade.py", "r", encoding="utf-8") as f:
        lines = f.readlines()

    script1_lines = []
    in_script1 = False
    start_line = 0

    for idx, line in enumerate(lines, 1):
        if "<script>" in line and not in_script1:
            in_script1 = True
            start_line = idx
            continue
        if "</script>" in line and in_script1:
            break
        if in_script1:
            script1_lines.append((idx, line))

    print(f"Script 1 spans lines {start_line} to {start_line + len(script1_lines)}")

    # Check syntax line by line by incrementally testing chunks to find where it breaks
    for count in range(1, len(script1_lines) + 1):
        chunk = "".join([l[1] for l in script1_lines[:count]])
        clean_code = re.sub(r'\{\{.*?\}\}', '1000', chunk)
        clean_code = re.sub(r'\{%.*?%\}', '', clean_code)

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(clean_code)
            tmp_path = tmp.name

        try:
            res = subprocess.run(["node", "--check", tmp_path], capture_output=True, text=True)
            err = res.stderr.strip()
            # If the error is NOT 'Unexpected end of input', print it!
            if "Unexpected end of input" not in err and "Unexpected token" in err:
                line_num = script1_lines[count-1][0]
                print(f"Syntax error near file line {line_num}: {err}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    find_script_lines()
