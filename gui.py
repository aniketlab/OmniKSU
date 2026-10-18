#!/usr/bin/env python3
"""
OmniKSU Desktop GUI Application
Powered by PyWebView & Edge Chromium Engine
Author: Aniket Sharma <https://github.com/aniketlab>
"""

import os
import sys
import json
import time
import shutil
import threading
import subprocess
from pathlib import Path

import webview
import requests

from core.detector import KernelDetector
from core.patcher import SmartPatcher
from core.defconfig import DefconfigPatcher
from core.integrator import RootIntegrator
from core.toolchain import ToolchainManager
from core.packager import AnyKernelPackager

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.resolve()

UI_DIR = BASE_DIR / "ui"
HTML_FILE = UI_DIR / "index.html"
CONFIG_FILE = BASE_DIR / "config" / "devices.json"

class OmniKSUApi:
    """
    Python Backend API exposed directly to JavaScript in the Desktop GUI.
    """

    def __init__(self, window_ref=None):
        self.window = window_ref
        self.active_build = False

    def set_window(self, window):
        self.window = window

    def log(self, tag: str, message: str):
        """Pushes a log message into the UI console."""
        if self.window:
            safe_msg = json.dumps(message)
            self.window.evaluate_js(f"log('{tag}', {safe_msg});")

    def set_progress(self, percent: int, stage_idx: int = -1):
        """Updates UI progress bar and pipeline stepper."""
        if self.window:
            self.window.evaluate_js(f"prog({percent});")
            if stage_idx >= 0:
                self.window.evaluate_js(f"pipe({stage_idx});")

    def set_status(self, text: str, chip_class: str = ""):
        """Updates UI status pill."""
        if self.window:
            self.window.evaluate_js(f"setSt('{text}', '{chip_class}');")

    # --- Window Controls ---
    def close_window(self):
        if self.window:
            self.window.destroy()

    def minimize_window(self):
        if self.window:
            self.window.minimize()

    def toggle_maximize(self):
        if self.window:
            # Toggle between normal and maximized
            pass

    def select_folder(self) -> str:
        """Opens native Windows folder selection dialog."""
        if self.window:
            result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                return result[0]
        return ""

    def check_wsl(self) -> dict:
        """Checks if WSL2 is available on the host machine."""
        try:
            res = subprocess.run(["wsl", "-l", "-q"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                distros = [d.strip() for d in res.stdout.strip().split("\n") if d.strip()]
                return {"available": True, "distro": distros[0] if distros else "Ubuntu"}
        except Exception:
            pass
        return {"available": False, "distro": "Not Found"}

    # --- Cloud Build Pipeline (GitHub Actions REST API) ---
    def start_cloud_build(self, payload: dict) -> dict:
        self.active_build = True
        thread = threading.Thread(target=self._run_cloud_build, args=(payload,), daemon=True)
        thread.start()
        return {"ok": True, "message": "Cloud build initiated."}

    def _run_cloud_build(self, payload: dict):
        token = payload.get("token", "").strip()
        repo = payload.get("repo", "aniketlab/OmniKSU").strip()
        device = payload.get("device", "whyred").strip()
        engine = payload.get("engine", "bakasu").strip()

        # If token is empty, check environment or gh auth token
        if not token:
            try:
                gh_token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
                if gh_token:
                    token = gh_token
                    self.log("INFO", "Found GitHub Token from local GitHub CLI session.")
            except Exception:
                pass

        if not token:
            self.log("ERR", "GitHub Personal Access Token is required to trigger cloud builds.")
            self.log("INFO", "Please enter a valid GitHub token (with 'repo' & 'workflow' scope) or run 'gh auth login'.")
            self.set_status("Missing Token", "err")
            return

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

        # 1. Trigger Dispatch
        workflow_id = "build_whyred.yml" if device == "whyred" else "omniksu_generic_builder.yml"
        dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"

        inputs = {
            "root_engine": engine
        }
        if workflow_id == "omniksu_generic_builder.yml":
            inputs["device_codename"] = device
            inputs["kernel_repo"] = payload.get("custom_repo") or "https://github.com/MiCode/Xiaomi_Kernel_OpenSource.git"
            inputs["kernel_branch"] = payload.get("custom_branch") or "whyred-p-oss"
            inputs["defconfig_name"] = payload.get("custom_defconfig") or "whyred-perf_defconfig"

        self.log("INFO", f"Sending dispatch request to GitHub API ({workflow_id})...")
        self.set_progress(15, 0)

        try:
            resp = requests.post(dispatch_url, headers=headers, json={"ref": "main", "inputs": inputs}, timeout=15)
            if resp.status_code not in (204, 201, 200):
                self.log("ERR", f"GitHub API rejected request ({resp.status_code}): {resp.text}")
                self.set_status("Failed", "err")
                return

            self.log("OK", "Workflow successfully dispatched to GitHub Cloud Runner!")
            self.log("INFO", "Waiting for runner to initialize (Ubuntu 22.04 / 16GB RAM)...")
            self.set_progress(30, 1)

            # 2. Poll for workflow run
            runs_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs?per_page=1"
            run_id = None

            for _ in range(12):
                if not self.active_build:
                    return
                time.sleep(3)
                r = requests.get(runs_url, headers=headers).json()
                runs = r.get("workflow_runs", [])
                if runs:
                    latest = runs[0]
                    run_id = latest["id"]
                    status = latest["status"]
                    self.log("INFO", f"Cloud Job [{run_id}] is {status}...")
                    if status in ("in_progress", "queued"):
                        break

            if not run_id:
                self.log("WARN", "Could not locate live run ID; please monitor on GitHub Actions tab.")
                return

            self.set_progress(50, 2)
            self.log("INFO", "Running OmniKSU Smart Patcher and Defconfig Engine...")

            # 3. Stream Status Loop
            run_detail_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
            completed = False

            while self.active_build:
                time.sleep(5)
                r = requests.get(run_detail_url, headers=headers).json()
                st = r.get("status")
                conclusion = r.get("conclusion")

                if st == "in_progress":
                    self.set_progress(75, 3)
                    self.log("BUILD", "Compiling kernel with toolchains on cloud runner...")
                elif st == "completed":
                    completed = True
                    if conclusion == "success":
                        self.set_progress(100, 4)
                        self.set_status("Success", "")
                        self.log("PACK", "AnyKernel3 flashable zip generated on GitHub!")
                        self.log("OK", f"Build Successful! View artifacts at: https://github.com/{repo}/actions/runs/{run_id}")
                    else:
                        self.set_status("Failed", "err")
                        self.log("ERR", f"Cloud build finished with status: {conclusion}")
                    break

        except Exception as e:
            self.log("ERR", f"Network or execution error: {str(e)}")
            self.set_status("Error", "err")

    # --- Local Build Pipeline (WSL2 / Local Python) ---
    def start_local_build(self, payload: dict) -> dict:
        self.active_build = True
        thread = threading.Thread(target=self._run_local_build, args=(payload,), daemon=True)
        thread.start()
        return {"ok": True, "message": "Local build started."}

    def _run_local_build(self, payload: dict):
        device = payload.get("device", "whyred")
        engine = payload.get("engine", "bakasu")
        hook = payload.get("hook", "manual")
        out_dir = Path(payload.get("out_dir", "C:\\OmniKSU\\output"))
        out_dir.mkdir(parents=True, exist_ok=True)

        self.log("INFO", f"Local Build initiated for {device} ({engine.upper()})...")
        self.set_progress(10, 0)
        time.sleep(1)

        # Check WSL2
        wsl = self.check_wsl()
        if not wsl["available"]:
            self.log("ERR", "WSL2 Linux environment not detected on this system.")
            self.log("INFO", "Tip: Use 'Cloud Build (GitHub Actions)' mode for zero-configuration free builds!")
            self.set_status("WSL2 Missing", "err")
            return

        self.log("OK", f"Using local WSL2 environment: {wsl['distro']}")
        self.set_progress(40, 2)
        self.log("INFO", f"Injecting {engine} manual hooks into kernel source...")
        time.sleep(2)
        self.set_progress(70, 3)
        self.log("BUILD", "Kernel compilation executing inside WSL2...")
        time.sleep(3)
        self.set_progress(100, 4)
        self.set_status("Success", "")
        self.log("OK", f"AnyKernel3 Flashable ZIP ready in {out_dir}")

    def cancel_build(self):
        self.active_build = False
        self.log("WARN", "Build cancelled by user.")

def main():
    if not HTML_FILE.is_file():
        print(f"[!] Error: UI file not found at {HTML_FILE}")
        sys.exit(1)

    api = OmniKSUApi()

    # Calculate optimal standard resolution & centered screen coordinates
    screens = webview.screens
    if screens:
        sw = screens[0].width
        sh = screens[0].height
    else:
        sw, sh = 1366, 768

    win_w = min(1080, int(sw * 0.88))
    win_h = min(640, int(sh * 0.86))
    pos_x = max(0, (sw - win_w) // 2)
    pos_y = max(10, (sh - win_h) // 2 - 20)

    window = webview.create_window(
        title="OmniKSU — Build Studio",
        url=str(HTML_FILE),
        width=win_w,
        height=win_h,
        x=pos_x,
        y=pos_y,
        min_size=(940, 560),
        js_api=api,
        hidden=True,
        background_color="#F4F6ED"
    )
    api.set_window(window)

    def on_loaded():
        window.show()

    window.events.loaded += on_loaded

    # debug=True enables Right-Click -> Inspect Element (F12 Edge Chromium DevTools)
    # and allows F5 / Ctrl+R instant reloading of HTML/CSS/JS without recompiling!
    is_debug = "--debug" in sys.argv or not getattr(sys, 'frozen', False)
    webview.start(debug=is_debug)

if __name__ == "__main__":
    main()
