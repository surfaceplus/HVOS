"""
HVOS V10 Launcher — Unified CLI Entry Point
=============================================
Alias to HVOS_V10/__main__.py

Usage: python run_hvos.py <command> [args]
"""

import sys, os, traceback

# Delegate to HVOS_V10/__main__.py
BASE = os.path.dirname(os.path.abspath(__file__))
main_path = os.path.join(BASE, "HVOS_V10", "__main__.py")

if __name__ == "__main__":
    # Copy all args except script name
    sys.argv[0] = main_path
    with open(main_path) as f:
        code = compile(f.read(), main_path, "exec")
    exec(code)
