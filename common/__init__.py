# common/__init__.py
# Makes 'common' a proper Python package.
# All modules are still importable via sys.path insertion for backward compatibility.
import os
import sys

COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
