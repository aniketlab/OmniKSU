import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

class KernelDetector:
    """
    Analyzes an Android Linux kernel source tree to extract version metadata,
    architecture parameters, and optimal root/hooking strategies.
    """

    def __init__(self, kernel_root: Path):
        self.kernel_root = Path(kernel_root).resolve()
        self.makefile_path = self.kernel_root / "Makefile"

    def is_valid_kernel_tree(self) -> bool:
        """Checks if the directory contains a standard Linux kernel source tree."""
        return (
            self.makefile_path.is_file() and 
            (self.kernel_root / "arch").is_dir() and 
            (self.kernel_root / "drivers").is_dir() and
            (self.kernel_root / "fs").is_dir()
        )

    def detect_version(self) -> Dict[str, Any]:
        """
        Parses top-level Makefile to extract VERSION, PATCHLEVEL, SUBLEVEL.
        """
        if not self.makefile_path.is_file():
            raise FileNotFoundError(f"Makefile not found in {self.kernel_root}")

        version_info = {
            "version": None,
            "patchlevel": None,
            "sublevel": None,
            "extraversion": "",
            "full_version": "unknown",
            "family": "unknown"
        }

        with open(self.makefile_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("VERSION ="):
                    version_info["version"] = int(line.split("=")[1].strip())
                elif line.startswith("PATCHLEVEL ="):
                    version_info["patchlevel"] = int(line.split("=")[1].strip())
                elif line.startswith("SUBLEVEL ="):
                    sublevel_str = line.split("=")[1].strip()
                    try:
                        version_info["sublevel"] = int(sublevel_str)
                    except ValueError:
                        version_info["sublevel"] = 0
                elif line.startswith("EXTRAVERSION ="):
                    version_info["extraversion"] = line.split("=")[1].strip()

                # Stop reading once we have the header values
                if (version_info["version"] is not None and 
                    version_info["patchlevel"] is not None and 
                    version_info["sublevel"] is not None):
                    break

        v = version_info["version"]
        p = version_info["patchlevel"]
        s = version_info["sublevel"]
        extra = version_info["extraversion"]

        if v is not None and p is not None:
            version_info["family"] = f"{v}.{p}"
            version_info["full_version"] = f"{v}.{p}.{s}{extra}"
        
        return version_info

    def get_recommended_strategy(self, version_info: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """
        Determines the best root engine, hook method, and toolchain recommendations.
        """
        if not version_info:
            version_info = self.detect_version()

        v = version_info.get("version")
        p = version_info.get("patchlevel")

        # Default fallback
        strategy = {
            "root_engine": "bakasu",
            "hook_mode": "manual",
            "toolchain": "clang-11",
            "is_gki": False,
            "reason": "Legacy non-GKI kernel requires manual syscall hooking."
        }

        if v == 3 or (v == 4 and p in (4, 9)):
            strategy["root_engine"] = "bakasu"
            strategy["hook_mode"] = "manual"
            strategy["toolchain"] = "gcc-4.9" if (v == 4 and p == 4) else "clang-10"
            strategy["reason"] = f"Kernel {v}.{p} lacks reliable tracepoint/kprobe syscall redirection. Manual hooks mandatory."
        elif v == 4 and p in (14, 19):
            strategy["root_engine"] = "bakasu"
            strategy["hook_mode"] = "manual"  # Manual is always safest on stock ROMs
            strategy["toolchain"] = "clang-12"
            strategy["reason"] = f"Kernel {v}.{p} can use manual hooks or kprobes; manual hooks ensure full Stock ROM compatibility."
        elif (v == 5 and p >= 10) or v >= 6:
            strategy["root_engine"] = "kernelsu-next"
            strategy["hook_mode"] = "kprobes"
            strategy["toolchain"] = "clang-r450784d"
            strategy["is_gki"] = True
            strategy["reason"] = "Modern GKI kernel with full tracepoint/kprobe support."
        
        return strategy
