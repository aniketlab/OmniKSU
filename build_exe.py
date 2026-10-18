#!/usr/bin/env python3
"""
OmniKSU Executable Builder
Compiles the Python + PyWebView GUI and Core Engine into a standalone OmniKSU.exe
Author: Aniket Sharma <https://github.com/aniketlab>
"""

import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
UI_DIR = BASE_DIR / "ui"
CONFIG_DIR = BASE_DIR / "config"

def build():
    print("========================================")
    print("[*] Building Standalone OmniKSU.exe...")
    print("========================================")

    # PyInstaller separator on Windows is ';'
    add_ui = f"{UI_DIR};ui"
    add_config = f"{CONFIG_DIR};config"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name", "OmniKSU",
        "--add-data", add_ui,
        "--add-data", add_config,
        "--clean",
        str(BASE_DIR / "gui.py")
    ]

    print(f"[*] Running command: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))

    if res.returncode == 0:
        exe_path = BASE_DIR / "dist" / "OmniKSU.exe"
        print("========================================")
        print(f"[✓] OmniKSU.exe successfully created at:")
        print(f"    {exe_path}")
        print("========================================")
    else:
        print("[!] Build failed.")
        sys.exit(1)

if __name__ == "__main__":
    build()
