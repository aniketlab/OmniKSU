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
            brand = run_getprop("ro.product.brand") or run_getprop("ro.product.manufacturer")
            android_ver = run_getprop("ro.build.version.release")
            miui_ver = run_getprop("ro.build.version.incremental")
            kernel_uname = run_cmd("uname -r")

            # Extract major.minor.sublevel from uname -r (e.g. 4.4.153-perf -> 4.4.153)
            kernel_match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", kernel_uname)
            kernel_family = "unknown"
            kernel_full = "unknown"
            if kernel_match:
                maj = kernel_match.group(1)
                min_v = kernel_match.group(2)
                sub_v = kernel_match.group(3) or "0"
                kernel_family = f"{maj}.{min_v}"
                kernel_full = f"{maj}.{min_v}.{sub_v}"

            is_stock_rom = bool(miui_ver or run_getprop("ro.miui.ui.version.name") or run_getprop("ro.oxygen.version"))

            # Check config/devices.json for verified hardware profile match
            config_file = Path(__file__).parent.parent / "config" / "devices.json"
            matched_preset = None
            if config_file.is_file():
                try:
                    import json
                    with open(config_file, "r", encoding="utf-8") as f:
                        presets = json.load(f).get("devices", {})
                        c_low = codename.lower()
                        for p_code, p_data in presets.items():
                            aliases = [a.lower() for a in p_data.get("anykernel_device_names", [])]
                            if p_code.lower() == c_low or c_low in aliases:
                                matched_preset = dict(p_data)
                                matched_preset["preset_id"] = p_code
                                break
                except Exception:
                    pass

            return {
                "connected": True,
                "serial": device_serial,
                "codename": codename,
                "model": model,
                "brand": brand,
                "android_version": android_ver,
                "miui_version": miui_ver,
                "is_stock_rom": is_stock_rom,
                "kernel_release": kernel_uname,
                "kernel_family": kernel_family,
                "kernel_full_version": kernel_full,
                "matched_preset": matched_preset
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

        # Ensure active_branch is unconditionally present in the branches list
        if active_branch and active_branch not in branches:
            branches.insert(0, active_branch)

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
        rationale = ""

        # Zero-guesswork Universal Android OS version detection
        android_target = cls.detect_android_version(
            branch_name=active_branch,
            repo_url_or_name=f"{owner}/{repo_name}",
            defconfig=defconfigs[0] if defconfigs else "",
            version_info=version_info
        )

        if v == 3 or (v == 4 and p in (4, 9)):
            rec_engine = "bakasu"
            rec_hook = "manual"
            rec_toolchain = "gcc-4.9"
            rationale = f"Linux {version_info['family']} legacy architecture targeting {android_target}. Configured with BakaSU for stable stock ROM root access."
        elif v == 4 and p in (14, 19):
            rec_engine = "kernelsu-next"
            rec_hook = "kprobes"
            rec_toolchain = "proton-clang"
            rationale = f"Linux {version_info['family']} architecture targeting {android_target}. Configured with KernelSU-Next via Kprobes dynamic hooking."
        elif v and v >= 5:
            rec_engine = "kernelsu-next"
            rec_hook = "kprobes"
            rec_toolchain = "proton-clang"
            rationale = f"Linux {version_info['family']} modern GKI architecture targeting {android_target}. Configured with KernelSU-Next via Kprobes."
        else:
            rationale = f"Linux {version_info.get('family', 'Custom')} kernel targeting {android_target}."

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
    def detect_android_version(
        cls,
        branch_name: str,
        repo_url_or_name: str = "",
        defconfig: str = "",
        version_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Intelligently identifies the exact Android OS version (Android 7 - 16)
        targeted by this kernel tree across all OEMs, AOSP, and Custom ROM schemes.
        Eliminates guesswork by analyzing branch naming patterns, OEM release tags,
        verified profile benchmarks, and kernel ABI architecture.
        """
        b = (branch_name or "").strip()
        b_low = b.lower()
        r_low = (repo_url_or_name or "").lower()
        d_low = (defconfig or "").lower()

        # 1. Check verified hardware presets (config/devices.json)
        config_file = Path(__file__).parent.parent / "config" / "devices.json"
        if config_file.is_file():
            try:
                import json
                with open(config_file, "r", encoding="utf-8") as f:
                    presets = json.load(f).get("devices", {})
                    for p_code, p_data in presets.items():
                        p_branch = p_data.get("branch", "").lower()
                        p_repo = p_data.get("repo_url", "").lower()
                        if p_branch and p_branch == b_low:
                            if not p_repo or p_repo in r_low or any(part in r_low for part in p_repo.split("/")[-2:]):
                                if p_data.get("tested_stock_os"):
                                    return p_data["tested_stock_os"]
            except Exception:
                pass

        # 2. OnePlus / Qualcomm OSS scheme: e.g. oneplus/SDM845_R_11.0, SM8150_Q_10.0, SM8350_T_13.0, SM8450_U_14.0
        m_op = re.search(r"[_/-]([A-Z])_([0-9]{1,2}(?:\.[0-9]+)?)", b)
        if m_op:
            letter = m_op.group(1).upper()
            ver_num = m_op.group(2)
            letter_map = {
                "N": "Nougat", "O": "Oreo", "P": "Pie", "Q": "Android 10 (Q)",
                "R": "Android 11 (R)", "S": "Android 12 (S)", "T": "Android 13 (T)",
                "U": "Android 14 (U)", "V": "Android 15 (V)", "W": "Android 16 (W)"
            }
            name = letter_map.get(letter, f"Android {ver_num}")
            if not name.startswith("Android"):
                return f"Android {ver_num} ({name})"
            return name

        # 3. Xiaomi / MiCode convention: e.g. tulip-p-oss, whyred-o-oss, mido-n-oss, marble-t-oss, alioth-r-oss, marble-u-oss
        m_mi = re.search(r"[_-]([a-z])-oss\b", b_low)
        if m_mi:
            mi_letter = m_mi.group(1)
            mi_map = {
                "n": "Android 7.0 - 7.1 (Nougat)",
                "o": "Android 8.0 - 8.1 (Oreo)",
                "p": "Android 9.0 (Pie)",
                "q": "Android 10 (Q)",
                "r": "Android 11 (R)",
                "s": "Android 12 (S)",
                "t": "Android 13 (T)",
                "u": "Android 14 (U)",
                "v": "Android 15 (V)"
            }
            if mi_letter in mi_map:
                return mi_map[mi_letter]

        # 4. LineageOS / CyanogenMod: e.g. lineage-18.1, lineage-20.0, lineage-21, cm-14.1
        m_los = re.search(r"(?:lineage|cm)[_-]([0-9]+(?:\.[0-9]+)?)", b_low)
        if m_los:
            try:
                los_ver = float(m_los.group(1))
                los_map = {
                    14.1: "Android 7.1 (Nougat)",
                    14.0: "Android 7.0 (Nougat)",
                    15.1: "Android 8.1 (Oreo)",
                    15.0: "Android 8.0 (Oreo)",
                    16.0: "Android 9.0 (Pie)",
                    17.1: "Android 10 (Q)",
                    17.0: "Android 10 (Q)",
                    18.1: "Android 11 (R)",
                    18.0: "Android 11 (R)",
                    19.1: "Android 12L (S)",
                    19.0: "Android 12 (S)",
                    20.0: "Android 13 (T)",
                    21.0: "Android 14 (U)",
                    22.0: "Android 15 (V)",
                    22.1: "Android 15 (V)",
                }
                if los_ver in los_map:
                    return los_map[los_ver]
                elif int(los_ver) == 20:
                    return "Android 13 (T)"
                elif int(los_ver) == 21:
                    return "Android 14 (U)"
                elif int(los_ver) >= 22:
                    return f"Android {int(los_ver) - 7} (V+)"
            except ValueError:
                pass

        # 5. Named Custom ROM / AOSP code names: e.g. fifteen, fourteen, thirteen, twelve-l, twelve, eleven, ten, pie, oreo
        named_map = {
            "fifteen": "Android 15 (V)",
            "fourteen": "Android 14 (U)",
            "thirteen": "Android 13 (T)",
            "twelve-l": "Android 12L (S)",
            "twelve": "Android 12 (S)",
            "eleven": "Android 11 (R)",
            "ten": "Android 10 (Q)",
            "pie": "Android 9.0 (Pie)",
            "oreo": "Android 8.1 (Oreo)",
            "nougat": "Android 7.1 (Nougat)"
        }
        for kw, target_name in named_map.items():
            if re.search(r"(?:^|[_\-/])" + kw + r"(?:[_\-/]|$)", b_low):
                return target_name

        # 6. Explicit numeric Android release pattern in branch or repo: e.g. android-11, android11, android-12.0.0_r32, AOSP android-msm-coral-4.14-android11
        and_map = {
            "7": "Android 7.0 - 7.1 (Nougat)",
            "8": "Android 8.0 - 8.1 (Oreo)",
            "9": "Android 9.0 (Pie)",
            "10": "Android 10 (Q)",
            "11": "Android 11 (R)",
            "12": "Android 12 (S)",
            "13": "Android 13 (T)",
            "14": "Android 14 (U)",
            "15": "Android 15 (V)",
            "16": "Android 16 (B)"
        }
        m_and = re.search(r"android[_-]?([0-9]{1,2})(?:\.([0-9]+))?", b_low)
        if m_and:
            maj = m_and.group(1)
            sub = m_and.group(2)
            if maj in and_map:
                if sub:
                    return f"Android {maj}.{sub}"
                return and_map[maj]

        # 7. Motorola mmi tag pattern: e.g. mmi-qp130 (Q=10), mmi-rp131 (R=11), mmi-s1 (S=12), mmi-t1 (T=13)
        m_mmi = re.search(r"mmi-([q-v])", b_low)
        if m_mmi:
            mmi_letter = m_mmi.group(1)
            mmi_map = {
                "q": "Android 10 (Q)",
                "r": "Android 11 (R)",
                "s": "Android 12 (S)",
                "t": "Android 13 (T)",
                "u": "Android 14 (U)",
                "v": "Android 15 (V)"
            }
            if mmi_letter in mmi_map:
                return mmi_map[mmi_letter]

        # 8. Standalone version prefix or suffix: e.g. v11.0, 11.0, 10.0, 12.0, 13.0, 14.0
        m_num = re.search(r"(?:^|[_\-/])(?:v)?(1[0-6]|[7-9])\.0(?:[_\-/]|$)", b_low)
        if m_num:
            num = m_num.group(1)
            if num in and_map:
                return and_map[num]

        # 9. Defconfig hints if branch had no clear signal
        if d_low:
            for kw, target_name in named_map.items():
                if kw in d_low:
                    return target_name
            m_def = re.search(r"[_\-]r([0-9]{1,2})[_\-]", d_low)
            if m_def and m_def.group(1) in and_map:
                return and_map[m_def.group(1)]

        # 10. Precise Linux Kernel LTS baseline architecture ranges
        if version_info:
            v = version_info.get("version")
            p = version_info.get("patchlevel")
            if v == 3:
                if p == 18:
                    return "Android 6.0 - 7.1 (Marshmallow / Nougat)"
                return "Android 4.4 - 6.0 (Legacy)"
            elif v == 4:
                if p in (4, 9):
                    return "Android 8.0 - 11.0 (Oreo - Android 11)"
                elif p in (14, 19):
                    return "Android 10.0 - 13.0 (Q - Android 13)"
            elif v == 5:
                if p in (4, 10):
                    return "Android 11.0 - 14.0 (R - Android 14)"
                elif p in (15,):
                    return "Android 13.0 - 15.0 (T - Android 15)"
            elif v and v >= 6:
                return "Android 14.0+ (Modern GKI)"

        return "Android 9.0 - 13.0"

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

    _SEARCH_CACHE: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def search_github_kernels(cls, query: Any, token: Optional[str] = None, phone_kernel: Optional[Any] = None, phone_brand: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        Searches candidate kernel repositories matching a device name or codename.
        Prioritizes verified official OEM profiles from config/devices.json,
        protects against GitHub API rate limits, and ranks authentic kernel sources.
        """
        # 1. Defensively sanitize all input types (e.g. if JS passes MouseEvent or dict)
        q = str(query or "").strip()
        if not q or q == "[object Object]":
            return []

        pk_str = str(phone_kernel or "") if not isinstance(phone_kernel, (dict, list)) else ""
        pb_str = str(phone_brand or "") if not isinstance(phone_brand, (dict, list)) else ""
        tok_str = str(token or "").strip() if not isinstance(token, (dict, list)) else ""

        cache_key = f"{q.lower()}::{pk_str}::{pb_str}"
        if cache_key in cls._SEARCH_CACHE:
            return cls._SEARCH_CACHE[cache_key]

        headers = dict(cls.HEADERS)
        if tok_str:
            headers["Authorization"] = f"token {tok_str}"

        q_lower = q.lower().replace("-", " ").replace("_", " ")
        q_tokens = [t for t in q_lower.split() if t]

        results: List[Dict[str, Any]] = []
        matched_codenames = set()
        matched_platforms = set()

        # 2. Check local verified database (config/devices.json) FIRST
        config_file = Path(__file__).parent.parent / "config" / "devices.json"
        if config_file.is_file():
            try:
                import json
                with open(config_file, "r", encoding="utf-8") as f:
                    presets = json.load(f).get("devices", {})
                    for p_code, p_data in presets.items():
                        p_name = p_data.get("name", "").lower()
                        p_aliases = [a.lower() for a in p_data.get("anykernel_device_names", [])]
                        p_plat = p_data.get("platform", "").lower()

                        is_match = (
                            p_code.lower() == q_lower or
                            p_code.lower() in q_tokens or
                            q_lower in p_name or
                            all(t in p_name.split() or t in p_name for t in q_tokens) or
                            any(q_lower == a or a in q_tokens for a in p_aliases)
                        )

                        if is_match:
                            matched_codenames.add(p_code.lower())
                            if p_plat:
                                matched_platforms.add(p_plat)
                            fn = "/".join(p_data["repo_url"].rstrip("/").split("/")[-2:])
                            if any(r["url"].lower() == p_data["repo_url"].lower() for r in results):
                                continue
                            results.append({
                                "name": fn.split("/")[-1],
                                "full_name": fn,
                                "url": p_data["repo_url"],
                                "clone_url": p_data["repo_url"],
                                "stars": 999,
                                "default_branch": p_data.get("branch", "main"),
                                "description": f"Verified official source for {p_data.get('name', p_code)} ({p_data.get('kernel_full_version', '')}) · {p_data.get('tested_stock_os', '')}",
                                "is_recommended": True,
                                "recommendation_reason": f"Official Profile ({p_data.get('name', p_code)})",
                                "detected_codename": p_code,
                                "target_defconfig": p_data.get("defconfig"),
                                "target_branch": p_data.get("branch")
                            })
            except Exception:
                pass

        # 3. Query GitHub Search API for community repositories
        primary_code = list(matched_codenames)[0] if matched_codenames else None
        primary_plat = list(matched_platforms)[0] if matched_platforms else None

        search_candidates = []
        if primary_code:
            search_candidates.append(f"android_kernel_{primary_code} in:name")
            if primary_plat:
                search_candidates.append(f"android_kernel_{primary_plat} in:name")
        else:
            q_clean = q.lower().replace(" ", "_")
            search_candidates.append(f"android_kernel_{q_clean} in:name")
            search_candidates.append(f"{q} kernel")

        trusted_orgs = [
            "lineageos", "pixelexperience-devices", "arrowos-devices", "evolution-x-devices",
            "crdroidandroid", "micode", "oneplusoss", "oneplus", "oneplus-10r", "oneplus-7t-pro-development",
            "cucumbermtk", "motorola", "realme-kernel-opensource", "sony", "asus-rog",
            "nothing-kernel", "radcolor", "ivon852"
        ]

        items_dict: Dict[str, Any] = {}
        # Pre-seed existing verified repos
        for r in results:
            items_dict[r["full_name"].lower()] = r

        rate_limited = False
        for sc in search_candidates[:2]:
            url = f"https://api.github.com/search/repositories?q={requests.utils.quote(sc)}&sort=stars&order=desc&per_page=8"
            try:
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    for it in r.json().get("items", []):
                        fn = it.get("full_name", "")
                        if fn and fn.lower() not in items_dict:
                            items_dict[fn.lower()] = it
                elif r.status_code == 403:
                    rate_limited = True
                    break
            except Exception:
                pass

        community_items = [it for fn, it in items_dict.items() if "stargazers_count" in it]

        def calculate_score(item: dict) -> int:
            stars = item.get("stargazers_count", 0)
            score = stars * 2
            full_name = item.get("full_name", "").lower()
            name = item.get("name", "").lower()
            desc = (item.get("description") or "").lower()

            # Target codename / platform bonus
            if primary_code and (primary_code in name or primary_code in desc):
                score += 500
            if primary_plat and (primary_plat in name or primary_plat in desc):
                score += 400

            # Penalize unrelated platform mismatches (e.g. sm8150 showing for sm8250 OnePlus 8 Pro)
            if primary_plat == "sm8250" and "sm8150" in full_name:
                score -= 800
            elif primary_plat == "sm8150" and "sm8250" in full_name:
                score -= 800

            # Verified maintainer bonus ONLY IF related to target query or platform
            for org in trusted_orgs:
                if full_name.startswith(org + "/"):
                    if not primary_code or primary_code in full_name or (primary_plat and primary_plat in full_name):
                        score += 350
                    break

            if "kernel" in name:
                score += 50
            if "kernel-source" in full_name or "kernel_source" in full_name or "bakasu" in full_name or "kernelsu" in full_name:
                score += 100

            # Deprioritize device/twrp trees
            if name.startswith("android_device_") or name.startswith("device_") or "twrp" in name or "vendor_" in name:
                score -= 400
            return score

        community_items.sort(key=calculate_score, reverse=True)

        for idx, item in enumerate(community_items[:8]):
            fn = item["full_name"]
            is_rec = (len(results) == 0 and idx == 0)
            det_codename = primary_code or cls.extract_codename_from_repo(item["name"], q)

            rec_reason = ""
            if is_rec:
                if any(fn.lower().startswith(o + "/") for o in trusted_orgs):
                    rec_reason = "Verified Community Maintainer"
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

        cls._SEARCH_CACHE[cache_key] = results
        return results
