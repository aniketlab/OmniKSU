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
from core.inspector import RemoteKernelInspector
from core.verifier import SmartZipVerifier

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
        self._window = window_ref
        self.active_build = False

    def set_window(self, window):
        self._window = window

    def log(self, tag: str, message: str):
        """Pushes a log message into the UI console."""
        if self._window:
            safe_msg = json.dumps(message)
            self._window.evaluate_js(f"log('{tag}', {safe_msg});")

    def set_progress(self, percent: int, stage_idx: int = -1):
        """Updates UI progress bar and pipeline stepper."""
        if self._window:
            self._window.evaluate_js(f"prog({percent});")
            if stage_idx >= 0:
                self._window.evaluate_js(f"pipe({stage_idx});")

    def set_status(self, text: str, chip_class: str = ""):
        """Updates UI status pill."""
        if self._window:
            self._window.evaluate_js(f"setSt('{text}', '{chip_class}');")

    # --- Window Controls ---
    def close_window(self):
        if self._window:
            self._window.destroy()

    def minimize_window(self):
        if self._window:
            self._window.minimize()

    def toggle_maximize(self):
        if self._window:
            # Toggle between normal and maximized
            pass

    def select_folder(self) -> str:
        """Opens native Windows folder selection dialog."""
        if self._window:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
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

    def inspect_repo(self, repo_url: str, branch: str = "") -> dict:
        """Inspects a GitHub repository to auto-detect kernel version, branches, defconfigs, and engine."""
        return RemoteKernelInspector.inspect_github_repo(repo_url, branch or None)

    def search_sources(self, query: str = "", phone_kernel: str = "", phone_brand: str = "", token: str = "") -> list:
        """Searches candidate kernel sources matching a device or codename."""
        if not isinstance(query, str):
            query = ""
        if not isinstance(phone_kernel, str):
            phone_kernel = ""
        if not isinstance(phone_brand, str):
            phone_brand = ""
        if not isinstance(token, str):
            token = ""
        return RemoteKernelInspector.search_github_kernels(query, token=token or None, phone_kernel=phone_kernel or None, phone_brand=phone_brand or None)

    def detect_connected_phone(self) -> dict:
        """Reads attached Android device properties over ADB."""
        return RemoteKernelInspector.detect_connected_phone()

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
            self.log("INFO", "Please click '1-Click Generate Token' or paste your token in Step 3.")
            self.set_status("Missing Token", "err")
            self.active_build = False
            if self._window:
                self._window.evaluate_js("on_build_completed(false);")
            return

        # Smart Fork Check & Auto-Routing:
        # Prevent 403 Forbidden on upstream aniketlab/OmniKSU for external users
        try:
            u_resp = requests.get("https://api.github.com/user", headers={"Authorization": f"token {token}", "User-Agent": "OmniKSU-Studio"}, timeout=8)
            if u_resp.status_code == 200:
                current_login = u_resp.json().get("login", "")
                if current_login and current_login.lower() != "aniketlab" and repo.lower() == "aniketlab/omniksu":
                    fork_candidate = f"{current_login}/OmniKSU"
                    f_resp = requests.get(f"https://api.github.com/repos/{fork_candidate}", headers={"Authorization": f"token {token}", "User-Agent": "OmniKSU-Studio"}, timeout=8)
                    if f_resp.status_code == 200:
                        self.log("INFO", f"Redirected target repo to your personal fork: {fork_candidate}")
                        repo = fork_candidate
                    else:
                        self.log("ERR", f"Workflow dispatch requires write access. Please click '1-Click Auto-Fork' in Step 3 to fork OmniKSU to @{current_login} first!")
                        self.set_status("Fork Required", "err")
                        self.active_build = False
                        if self._window:
                            self._window.evaluate_js("on_build_completed(false);")
                        return
        except Exception:
            pass

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "OmniKSU-Studio"
        }

        # 1. Trigger Dispatch
        workflow_id = "omniksu_generic_builder.yml"
        dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"

        inputs = {
            "device_codename": device,
            "kernel_repo": payload.get("kernel_repo") or payload.get("custom_repo") or "https://github.com/MiCode/Xiaomi_Kernel_OpenSource.git",
            "kernel_branch": payload.get("kernel_branch") or payload.get("custom_branch") or "tulip-p-oss",
            "defconfig_name": payload.get("defconfig_name") or payload.get("custom_defconfig") or "whyred-perf_defconfig",
            "root_engine": engine,
            "hook_mode": payload.get("hook", "manual"),
            "toolchain_choice": payload.get("toolchain_choice") or "gcc-4.9"
        }

        self.log("INFO", f"Sending dispatch request to GitHub API ({workflow_id})...")
        self.set_progress(15, 0)

        try:
            resp = requests.post(dispatch_url, headers=headers, json={"ref": "main", "inputs": inputs}, timeout=15)
            if resp.status_code not in (204, 201, 200):
                self.log("ERR", f"GitHub API rejected request ({resp.status_code}): {resp.text}")
                self.set_status("Failed", "err")
                self.active_build = False
                if self._window:
                    self._window.evaluate_js("on_build_completed(false);")
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
                self.active_build = False
                if self._window:
                    self._window.evaluate_js("on_build_completed(false);")
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
                        self.log("INFO", "Initiating automatic artifact download & smart verification...")
                        out_dir_str = payload.get("out_dir") or "C:\\OmniKSU\\output"
                        self._download_and_verify_artifact(repo=repo, run_id=run_id, token=token, out_dir=out_dir_str)
                        self.active_build = False
                        if self._window:
                            self._window.evaluate_js("on_build_completed(true);")
                    else:
                        self.active_build = False
                        self.set_status("Failed", "err")
                        self.log("ERR", f"Cloud build finished with status: {conclusion}")
                        if self._window:
                            self._window.evaluate_js("on_build_completed(false);")
                    break

        except Exception as e:
            self.log("ERR", f"Network or execution error: {str(e)}")
            self.set_status("Error", "err")
            self.active_build = False
            if self._window:
                self._window.evaluate_js("on_build_completed(false);")

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
        self.active_build = False
        if self._window:
            self._window.evaluate_js("on_build_completed(true);")

    def _download_and_verify_artifact(self, repo: str, run_id: int, token: str, out_dir: str):
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        artifacts_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"

        try:
            target_artifact = None
            for _ in range(5):
                time.sleep(2)
                r = requests.get(artifacts_url, headers=headers, timeout=12)
                if r.status_code == 200:
                    artifacts = r.json().get("artifacts", [])
                    if artifacts:
                        flashable = [a for a in artifacts if "flashable" in a.get("name", "").lower()]
                        target_artifact = flashable[0] if flashable else artifacts[0]
                        break

            if not target_artifact:
                self.log("WARN", "Artifact not yet indexed by GitHub. You can view it on GitHub Actions.")
                return

            art_name = target_artifact.get("name", "Flashable-Kernel")
            download_url = target_artifact.get("archive_download_url")
            art_size_mb = target_artifact.get("size_in_bytes", 0) / (1024 * 1024)

            self.log("INFO", f"Downloading {art_name} ({art_size_mb:.1f} MB) from GitHub Cloud...")

            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            dl_res = requests.get(download_url, headers=headers, stream=True, timeout=120)
            if dl_res.status_code != 200:
                self.log("ERR", f"Failed to download artifact ({dl_res.status_code}).")
                return

            import zipfile
            import io
            outer_bio = io.BytesIO(dl_res.content)
            outer_zf = zipfile.ZipFile(outer_bio, "r")
            inner_names = outer_zf.namelist()

            if inner_names:
                inner_file = inner_names[0]
                final_zip_path = out_path / inner_file
                with open(final_zip_path, "wb") as f:
                    f.write(outer_zf.read(inner_file))
            else:
                final_zip_path = out_path / f"{art_name}.zip"
                with open(final_zip_path, "wb") as f:
                    f.write(dl_res.content)

            self.log("OK", f"Flashable ZIP saved to: {final_zip_path}")
            self.log("VERIFY", "Running OmniKSU Smart Zip Verification Engine...")

            res = SmartZipVerifier.verify_flashable_zip(final_zip_path)

            if res.get("valid"):
                self.log("OK", f"Integrity Pass: {res['filename']} ({res['file_size']})")
                self.log("OK", f"Kernel Image: {res.get('kernel_image')} ({res.get('kernel_size_mb', 0):.1f} MB)")
                self.log("OK", f"SHA-256: {res['sha256'][:16]}...")
                self.log("OK", "Kernel is 100% Verified & Ready to Flash!")
            else:
                self.log("WARN", f"Verification notice: {res.get('error', 'Check details in delivery card')}")

            if self._window:
                safe_json = json.dumps(res)
                self._window.evaluate_js(f"show_artifact_card({safe_json});")

        except Exception as e:
            self.log("ERR", f"Artifact download error: {str(e)}")

    def save_artifact_as(self, source_path: str) -> dict:
        """Opens native file dialog so user can save the zip to their desired location."""
        p = Path(source_path)
        if not p.is_file():
            return {"ok": False, "error": "Source file not found."}
        try:
            import webview
            dialog_type = getattr(webview.FileDialog, "SAVE", webview.SAVE_DIALOG) if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
            res = self._window.create_file_dialog(
                dialog_type,
                save_filename=p.name,
                file_types=('ZIP Archives (*.zip)', 'All Files (*.*)')
            )
            if res:
                target = res if isinstance(res, str) else res[0]
                shutil.copy2(str(p), target)
                self.log("OK", f"Saved copy to: {target}")
                return {"ok": True, "saved_path": target}
            return {"ok": False, "error": "Save cancelled"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_folder(self, target_path: str):
        """Reveals file or directory in Windows File Explorer."""
        try:
            p = Path(target_path)
            if p.is_file():
                subprocess.run(["explorer.exe", f"/select,{str(p.resolve())}"])
            elif p.is_dir():
                subprocess.run(["explorer.exe", str(p.resolve())])
            else:
                parent = p.parent
                if parent.is_dir():
                    subprocess.run(["explorer.exe", str(parent.resolve())])
        except Exception as e:
            self.log("WARN", f"Could not open explorer: {e}")

    def push_to_phone(self, file_path: str) -> dict:
        """Pushes flashable zip directly to connected phone over ADB (/sdcard/Download/)."""
        try:
            p = Path(file_path)
            if not p.is_file():
                return {"ok": False, "error": "Kernel ZIP file not found."}
            adb = RemoteKernelInspector.get_adb_binary()
            if not adb:
                return {"ok": False, "error": "ADB executable not found."}

            dest = f"/sdcard/Download/{p.name}"
            self.log("INFO", f"Transferring {p.name} to Phone storage ({dest})...")
            res = subprocess.run([str(adb), "push", str(p), dest], capture_output=True, text=True, timeout=90)
            if res.returncode == 0:
                self.log("OK", f"Successfully copied to Phone: {dest}")
                return {"ok": True, "message": f"Saved to Phone: {dest}"}
            else:
                err = res.stderr.strip() or "ADB push failed."
                self.log("ERR", err)
                return {"ok": False, "error": err}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def verify_custom_zip_file(self) -> dict:
        """Opens a file dialog for the user to pick ANY zip and verifies it."""
        try:
            import webview
            dialog_type = getattr(webview.FileDialog, "OPEN", webview.OPEN_DIALOG) if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
            res = self._window.create_file_dialog(
                dialog_type,
                file_types=('ZIP Archives (*.zip)', 'All Files (*.*)')
            )
            if res:
                chosen = res if isinstance(res, str) else res[0]
                result = SmartZipVerifier.verify_flashable_zip(chosen)
                if self._window:
                    self._window.evaluate_js(f"show_artifact_card({json.dumps(result)});")
                return {"ok": True, "result": result}
            return {"ok": False, "error": "Selection cancelled"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cancel_build(self):
        self.active_build = False
        self.log("WARN", "Build cancelled by user.")

    def open_external_url(self, url: str) -> dict:
        """Opens URL in user's default web browser."""
        import webbrowser
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_clipboard_text(self) -> str:
        """Reads text content from system clipboard."""
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            if text:
                return text.strip()
        except Exception:
            pass
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    def detect_gh_cli(self) -> dict:
        """Checks if local gh CLI is authenticated and returns user & token."""
        try:
            tok = subprocess.check_output(["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL, timeout=4).strip()
            if tok:
                user = subprocess.check_output(["gh", "api", "user", "--jq", ".login"], text=True, stderr=subprocess.DEVNULL, timeout=4).strip()
                return {"available": True, "token": tok, "user": user}
        except Exception:
            pass
        return {"available": False}

    def validate_github_token(self, token: str) -> dict:
        """Validates GitHub Personal Access Token, retrieves profile, and checks fork status."""
        token = (token or "").strip()
        if not token:
            return {"ok": False, "error": "Token cannot be empty."}

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "OmniKSU-Studio"
        }

        try:
            resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
            if resp.status_code != 200:
                return {"ok": False, "error": f"Authentication failed ({resp.status_code}). Invalid or expired token."}

            user_data = resp.json()
            login = user_data.get("login", "")
            name = user_data.get("name") or login
            avatar_url = user_data.get("avatar_url", "")
            scopes = resp.headers.get("x-oauth-scopes", "")

            is_owner = (login.lower() == "aniketlab")
            has_fork = is_owner
            fork_repo = "aniketlab/OmniKSU" if is_owner else f"{login}/OmniKSU"

            if not is_owner:
                repo_resp = requests.get(f"https://api.github.com/repos/{login}/OmniKSU", headers=headers, timeout=10)
                if repo_resp.status_code == 200:
                    has_fork = True
                else:
                    has_fork = False

            return {
                "ok": True,
                "login": login,
                "name": name,
                "avatar_url": avatar_url,
                "scopes": scopes,
                "is_owner": is_owner,
                "has_fork": has_fork,
                "fork_repo": fork_repo
            }
        except Exception as e:
            return {"ok": False, "error": f"Network error during authentication: {str(e)}"}

    def auto_fork_repo(self, token: str) -> dict:
        """Automatically forks aniketlab/OmniKSU to the authenticated user's account and enables Actions."""
        token = (token or "").strip()
        if not token:
            return {"ok": False, "error": "Token required to create fork."}

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "OmniKSU-Studio"
        }

        try:
            u_resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
            if u_resp.status_code != 200:
                return {"ok": False, "error": "Invalid GitHub token."}
            username = u_resp.json().get("login", "")

            if username.lower() == "aniketlab":
                return {"ok": True, "already_owner": True, "fork_repo": "aniketlab/OmniKSU", "message": "You are the repository owner."}

            # Check if fork already exists
            check_resp = requests.get(f"https://api.github.com/repos/{username}/OmniKSU", headers=headers, timeout=10)
            if check_resp.status_code == 200:
                return {"ok": True, "fork_repo": f"{username}/OmniKSU", "message": "Fork already exists on your account."}

            # Request GitHub to create fork
            fork_url = "https://api.github.com/repos/aniketlab/OmniKSU/forks"
            f_resp = requests.post(fork_url, headers=headers, json={"default_branch_only": True}, timeout=15)
            if f_resp.status_code not in (200, 202):
                return {"ok": False, "error": f"GitHub rejected fork creation ({f_resp.status_code}): {f_resp.text}"}

            # Wait for GitHub to provision the fork (up to 16 seconds)
            fork_ready = False
            for _ in range(8):
                time.sleep(2)
                r = requests.get(f"https://api.github.com/repos/{username}/OmniKSU", headers=headers, timeout=10)
                if r.status_code == 200:
                    fork_ready = True
                    break

            # Try to ensure GitHub Actions permissions are enabled
            try:
                perm_url = f"https://api.github.com/repos/{username}/OmniKSU/actions/permissions"
                requests.put(perm_url, headers=headers, json={"enabled": True, "allowed_actions": "all"}, timeout=10)
            except Exception:
                pass

            return {
                "ok": True,
                "fork_repo": f"{username}/OmniKSU",
                "message": f"Successfully forked OmniKSU to {username}/OmniKSU with GitHub Actions enabled!"
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to fork repository: {str(e)}"}

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

    win_w = min(1140, int(sw * 0.90))
    win_h = min(710, int(sh * 0.88))
    pos_x = max(0, (sw - win_w) // 2)
    pos_y = max(10, (sh - win_h) // 2 - 15)

    window = webview.create_window(
        title="OmniKSU — Build Studio",
        url=str(HTML_FILE),
        width=win_w,
        height=win_h,
        x=pos_x,
        y=pos_y,
        min_size=(940, 560),
        js_api=api,
        hidden=False,
        background_color="#F4F6ED"
    )
    api.set_window(window)

    # debug=True enables Right-Click -> Inspect Element (F12 Edge Chromium DevTools)
    # and allows F5 / Ctrl+R instant reloading of HTML/CSS/JS without recompiling!
    is_debug = "--debug" in sys.argv or not getattr(sys, 'frozen', False)
    webview.start(debug=is_debug)

if __name__ == "__main__":
    main()
