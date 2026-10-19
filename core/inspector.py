import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import requests

class RemoteKernelInspector:
    """
    Intelligent GitHub Repository and Local ADB Device Inspector for OmniKSU.
    Automatically discovers kernel versions, branches, defconfigs, and
    target Android compatibility without requiring manual user input.
    """

    HEADERS = {
        "User-Agent": "OmniKSU-Studio/1.0"
    }

    # Common ADB paths on Windows
    ADB_PATHS = [
        Path(r"C:\Users\sharm\Downloads\platform-tools\adb.exe"),
        Path(r"C:\platform-tools\adb.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    ]

    @classmethod
    def get_adb_binary(cls) -> Optional[Path]:
        """Locates the ADB executable on the host system."""
        for p in cls.ADB_PATHS:
            if p.is_file():
                return p
        system_adb = shutil.which("adb")
        if system_adb:
            return Path(system_adb)
        return None

    @classmethod
    def detect_connected_phone(cls) -> Dict[str, Any]:
        """
        Polls ADB to extract connected phone details (codename, model, kernel, Android version).
        """
        adb = cls.get_adb_binary()
        if not adb:
            return {"connected": False, "error": "ADB executable not found on system."}

        try:
            # 1. Check if device is attached
            res = subprocess.run([str(adb), "devices"], capture_output=True, text=True, timeout=4)
            lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
            attached = [l for l in lines[1:] if "device" in l and not "offline" in l]

            if not attached:
                return {"connected": False, "error": "No authorized device connected via USB ADB."}

            device_serial = attached[0].split()[0]

            # 2. Extract properties
            def run_getprop(prop: str) -> str:
                r = subprocess.run([str(adb), "-s", device_serial, "shell", "getprop", prop],
                                   capture_output=True, text=True, timeout=3)
                return r.stdout.strip()

            def run_cmd(cmd: str) -> str:
                r = subprocess.run([str(adb), "-s", device_serial, "shell", cmd],
                                   capture_output=True, text=True, timeout=3)
                return r.stdout.strip()

            codename = run_getprop("ro.product.device") or run_getprop("ro.build.product")
            model = run_getprop("ro.product.model") or codename
            android_ver = run_getprop("ro.build.version.release")
            miui_ver = run_getprop("ro.build.version.incremental")
            kernel_uname = run_cmd("uname -r")

            # Extract major.minor from uname -r (e.g. 4.4.153-perf -> 4.4)
            kernel_match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", kernel_uname)
            kernel_family = f"{kernel_match.group(1)}.{kernel_match.group(2)}" if kernel_match else "unknown"

            return {
                "connected": True,
                "serial": device_serial,
                "codename": codename,
                "model": model,
                "android_version": android_ver,
                "miui_version": miui_ver,
                "kernel_release": kernel_uname,
                "kernel_family": kernel_family
            }

        except Exception as e:
            return {"connected": False, "error": str(e)}

    @classmethod
    def parse_github_url(cls, url: str) -> Tuple[str, str, Optional[str]]:
        """Parses owner, repo, and optional branch from a GitHub URL."""
        clean_url = url.strip()
        if clean_url.endswith(".git"):
            clean_url = clean_url[:-4]

        # Match github.com/owner/repo or github.com/owner/repo/tree/branch
        pattern = r"github\.com[/:]([^/]+)/([^/]+)(?:/tree/([^/]+))?"
        match = re.search(pattern, clean_url)
        if match:
            owner = match.group(1)
            repo = match.group(2)
            branch = match.group(3)
            return owner, repo, branch

        parts = clean_url.split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1], None

        raise ValueError(f"Could not parse GitHub repository from URL: {url}")

    @classmethod
    def inspect_github_repo(cls, repo_url: str, selected_branch: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
        """
        Deep-inspects a remote GitHub repository to extract:
        - Kernel Version (via raw Makefile)
        - Branches list
        - Defconfigs list (via arch/arm64/configs)
        - Engine recommendation (BakaSU vs KSU-Next)
        - Toolchain recommendation (GCC 4.9 vs Clang)
        - Android compatibility assessment
        """
        try:
            owner, repo_name, url_branch = cls.parse_github_url(repo_url)
        except Exception as e:
            return {"ok": False, "error": str(e)}

        headers = dict(cls.HEADERS)
        if token:
            headers["Authorization"] = f"token {token}"

        api_base = f"https://api.github.com/repos/{owner}/{repo_name}"

        # 1. Fetch repository metadata (Default Branch, etc.)
        try:
            repo_res = requests.get(api_base, headers=headers, timeout=10)
            if repo_res.status_code == 404:
                return {"ok": False, "error": f"Repository '{owner}/{repo_name}' not found or is private."}
            repo_data = repo_res.json()
            default_branch = repo_data.get("default_branch", "main")
        except Exception:
            default_branch = "main"

        active_branch = selected_branch or url_branch or default_branch

        # 2. Fetch branches list (first 100 branches)
        branches = []
        try:
            b_res = requests.get(f"{api_base}/branches?per_page=100", headers=headers, timeout=10)
            if b_res.status_code == 200:
                branches = [b["name"] for b in b_res.json()]
        except Exception:
            pass

        if not active_branch:
            active_branch = default_branch if default_branch in branches else (branches[0] if branches else "main")

        # 3. Fetch top-level Makefile to extract Kernel Version
        raw_makefile_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{active_branch}/Makefile"
        version_info = {
            "version": None,
            "patchlevel": None,
            "sublevel": None,
            "full_version": "unknown",
            "family": "unknown"
        }

        try:
            mf_res = requests.get(raw_makefile_url, headers=headers, timeout=10)
            if mf_res.status_code == 200:
                for line in mf_res.text.splitlines():
                    line = line.strip()
                    if line.startswith("VERSION ="):
                        version_info["version"] = int(line.split("=")[1].strip())
                    elif line.startswith("PATCHLEVEL ="):
                        version_info["patchlevel"] = int(line.split("=")[1].strip())
                    elif line.startswith("SUBLEVEL ="):
                        try:
                            version_info["sublevel"] = int(line.split("=")[1].strip())
                        except ValueError:
                            version_info["sublevel"] = 0

                    if version_info["version"] and version_info["patchlevel"] and version_info["sublevel"] is not None:
                        break

                v = version_info["version"]
                p = version_info["patchlevel"]
                s = version_info["sublevel"]
                if v and p:
                    version_info["family"] = f"{v}.{p}"
                    version_info["full_version"] = f"{v}.{p}.{s}"
        except Exception:
            pass

        # 4. Fetch list of defconfigs (using recursive git tree to include vendor/ and subdirectories)
        defconfigs = []
        try:
            tree_api = f"{api_base}/git/trees/{active_branch}?recursive=1"
            tree_res = requests.get(tree_api, headers=headers, timeout=12)
            if tree_res.status_code == 200:
                tree_items = tree_res.json().get("tree", [])
                for item in tree_items:
                    p = item.get("path", "")
                    if (p.startswith("arch/arm64/configs/") or p.startswith("arch/arm/configs/")) and p.endswith("_defconfig"):
                        clean_cfg = p.split("/configs/", 1)[1]
                        # Filter out virtual/emulator/debug configs
                        if not any(bad in clean_cfg.lower() for bad in ["cuttlefish", "goldfish", "ranchu", "dummy", "test", "misc_debug"]):
                            defconfigs.append(clean_cfg)
        except Exception:
            pass

        # Fallback to contents API if tree API failed or was truncated
        if not defconfigs:
            for arch in ["arm64", "arm"]:
                try:
                    configs_api = f"{api_base}/contents/arch/{arch}/configs?ref={active_branch}"
                    cfg_res = requests.get(configs_api, headers=headers, timeout=10)
                    if cfg_res.status_code == 200 and isinstance(cfg_res.json(), list):
                        for f in cfg_res.json():
                            fname = f.get("name", "")
                            if fname.endswith("_defconfig") and not any(b in fname.lower() for b in ["cuttlefish", "goldfish", "ranchu"]):
                                defconfigs.append(fname)
                            elif f.get("type") == "dir" and fname == "vendor":
                                # Scan vendor subdirectory
                                v_res = requests.get(f"{configs_api}/vendor", headers=headers, timeout=10)
                                if v_res.status_code == 200 and isinstance(v_res.json(), list):
                                    for vf in v_res.json():
                                        vfname = vf.get("name", "")
                                        if vfname.endswith("_defconfig"):
                                            defconfigs.append(f"vendor/{vfname}")
                except Exception:
                    pass

        # 5. Smart Ranking of Defconfigs
        def score_defconfig(cfg: str) -> int:
            s = 0
            c_low = cfg.lower()
            if "-perf" in c_low or "_perf" in c_low:
                s += 100
            if c_low.startswith("vendor/"):
                s += 50
            if "gki" in c_low:
                s += 30
            return s

        defconfigs.sort(key=score_defconfig, reverse=True)

        # 6. Smart Heuristics & Recommendations
        v = version_info.get("version")
        p = version_info.get("patchlevel")

        rec_engine = "bakasu"
        rec_hook = "manual"
        rec_toolchain = "gcc-4.9"
        android_target = "Android 9 (Pie)"
        rationale = ""

        if v == 3 or (v == 4 and p in (4, 9)):
            rec_engine = "bakasu"
            rec_hook = "manual"
            rec_toolchain = "gcc-4.9"
            android_target = "Android 8.0 - 9.0 (Oreo / Pie)"
            rationale = f"Linux {version_info['family']} kernel detected. BakaSU with atomic pointer swap is required to prevent stop_machine SELinux boot deadlocks."
        elif v == 4 and p in (14, 19):
            rec_engine = "kernelsu-next"
            rec_hook = "kprobes"
            rec_toolchain = "proton-clang"
            android_target = "Android 10.0 - 12.0 (Q / R / S)"
            rationale = f"Linux {version_info['family']} kernel detected. KernelSU-Next with Kprobes fully supported; dual builds (Both) also available."
        elif v and v >= 5:
            rec_engine = "kernelsu-next"
            rec_hook = "kprobes"
            rec_toolchain = "proton-clang"
            android_target = "Android 12.0 - 14.0 (GKI / Modern)"
            rationale = f"Linux {version_info['family']} modern GKI kernel detected. KernelSU-Next with Kprobes fully supported."

        return {
            "ok": True,
            "owner": owner,
            "repo": repo_name,
            "active_branch": active_branch,
            "branches": branches,
            "defconfigs": defconfigs,
            "version_info": version_info,
            "recommended_engine": rec_engine,
            "recommended_hook": rec_hook,
            "recommended_toolchain": rec_toolchain,
            "android_target": android_target,
            "rationale": rationale
        }

    @classmethod
    def extract_codename_from_repo(cls, name: str, query: str) -> str:
        """Extracts a clean device codename or SoC from repository name or user query."""
        name_clean = name.lower()
        patterns = [
            r"(?:android_)?kernel_[a-z0-9]+_([a-z0-9_-]+)",
            r"(?:android_)?device_[a-z0-9]+_([a-z0-9_-]+)",
            r"kernel-([a-z0-9_-]+)",
            r"([a-z0-9_-]+)-kernel",
            r"android_([a-z0-9_-]+)-kernel",
        ]
        for pat in patterns:
            m = re.search(pat, name_clean)
            if m and m.group(1):
                cand = m.group(1).replace("-kernel", "").replace("_kernel", "").strip("-_")
                if cand and cand not in ("kernel", "common", "android", "platform", "modules", "mainline"):
                    return cand

        q_clean = query.strip().lower()
        parts = q_clean.split()
        if len(parts) == 1:
            return parts[0]
        return re.sub(r"[^a-z0-9_]+", "_", q_clean).strip("_")

    @classmethod
    def search_github_kernels(cls, query: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Searches GitHub for candidate kernel repositories matching a device name or codename.
        Ranks verified maintainers (LineageOS, PixelExperience, OEM orgs) as recommended.
        """
        q = query.strip()
        if not q:
            return []

        headers = dict(cls.HEADERS)
        if token:
            headers["Authorization"] = f"token {token}"

        trusted_orgs = [
            "lineageos", "pixelexperience-devices", "arrowos-devices", "evolution-x-devices",
            "crdroidandroid", "micode", "oneplus", "oneplus-10r", "oneplus-7t-pro-development",
            "cucumbermtk", "motorola", "realme-kernel-opensource", "sony", "asus-rog",
            "nothing-kernel", "radcolor", "ivon852"
        ]

        q_clean = q.lower().replace(" ", "_")
        q_hyphen = q.lower().replace(" ", "-")

        search_candidates = [
            f"android_kernel_{q_clean} in:name",
            f"kernel_{q_clean} in:name",
            f"{q} kernel",
            f"{q} android",
            f"{q}"
        ]

        items_dict = {}
        for sc in search_candidates:
            url = f"https://api.github.com/search/repositories?q={requests.utils.quote(sc)}&sort=stars&order=desc&per_page=6"
            try:
                r = requests.get(url, headers=headers, timeout=6)
                if r.status_code == 200:
                    for it in r.json().get("items", []):
                        fn = it.get("full_name", "")
                        if fn and fn not in items_dict:
                            items_dict[fn] = it
                if len(items_dict) >= 8:
                    break
            except Exception:
                pass

        items = list(items_dict.values())

        def calculate_score(item: dict) -> int:
            stars = item.get("stargazers_count", 0)
            score = stars * 3
            full_name = item.get("full_name", "").lower()
            name = item.get("name", "").lower()
            q_simple = q.lower().replace(" ", "").replace("_", "").replace("-", "")

            for org in trusted_orgs:
                if full_name.startswith(org + "/"):
                    score += 300
                    break

            if q_simple in full_name:
                score += 150
            if "kernel" in full_name:
                score += 50
            if "kernel-source" in full_name or "kernel_source" in full_name or "bakasu" in full_name or "kernelsu" in full_name:
                score += 120
            # Deprioritize device/twrp trees that are not full kernel sources
            if name.startswith("android_device_") or name.startswith("device_") or "twrp" in name:
                score -= 200
            return score

        items.sort(key=calculate_score, reverse=True)

        results = []
        for idx, item in enumerate(items[:10]):
            fn = item["full_name"]
            is_rec = (idx == 0)
            det_codename = cls.extract_codename_from_repo(item["name"], q)

            rec_reason = ""
            if is_rec:
                if any(fn.lower().startswith(o + "/") for o in trusted_orgs):
                    rec_reason = "Verified Community / OEM Maintainer"
                else:
                    rec_reason = f"Top Match ({item['stargazers_count']}★)"

            results.append({
                "name": item["name"],
                "full_name": fn,
                "url": item["html_url"],
                "clone_url": item["clone_url"],
                "stars": item["stargazers_count"],
                "default_branch": item["default_branch"],
                "description": item.get("description") or "Android Linux kernel source",
                "is_recommended": is_rec,
                "recommendation_reason": rec_reason,
                "detected_codename": det_codename
            })
        return results
