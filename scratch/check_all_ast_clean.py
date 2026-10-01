import ast
import glob
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

def check_all_ast():
    py_files = []
    for root, dirs, files in os.walk('.'):
        if any(x in root for x in ['.git', 'venv', '__pycache__', '.agents']):
            continue
        for f in files:
            if f.endswith('.py'):
                py_files.append(os.path.join(root, f))

    print(f"=== RUNNING AST SYNTAX AUDIT ON ALL {len(py_files)} PYTHON FILES ===")
    errors = []
    for f in py_files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                code = fp.read()
            ast.parse(code, filename=f)
        except Exception as e:
            errors.append((f, str(e)))

    if not errors:
        print(f"SUCCESS: 100% PASS! All {len(py_files)} Python files compiled cleanly with ZERO syntax errors!")
    else:
        print(f"FAILED: Found {len(errors)} syntax errors:")
        for f, err in errors:
            print(f"  {f}: {err}")

if __name__ == '__main__':
    check_all_ast()
