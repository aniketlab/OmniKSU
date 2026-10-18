import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

class DefconfigPatcher:
    """
    Automates the updating and tuning of target kernel defconfigs for
    KernelSU-Next / BakaSU integration on stock OEM firmware.
    """

    MANDATORY_FLAGS = {
        "CONFIG_KSU": "y",
        "CONFIG_OVERLAY_FS": "y",
    }

    MANUAL_HOOK_FLAGS = {
        "CONFIG_KSU_MANUAL_HOOK": "y",
    }

    SAFETY_FLAGS = {
        "CONFIG_MODULE_SIG_FORCE": "n",  # Prevents stock WiFi/Audio module signature panics
    }

    def __init__(self, defconfig_path: Path):
        self.defconfig_path = Path(defconfig_path).resolve()

    def patch(self, manual_hook: bool = True, enable_debug: bool = False) -> Tuple[bool, List[str]]:
        """
        Parses and injects required flags into the defconfig file.
        """
        if not self.defconfig_path.is_file():
            return False, [f"Defconfig not found at {self.defconfig_path}"]

        target_flags = dict(self.MANDATORY_FLAGS)
        if manual_hook:
            target_flags.update(self.MANUAL_HOOK_FLAGS)
        target_flags.update(self.SAFETY_FLAGS)

        target_flags["CONFIG_KSU_DEBUG"] = "y" if enable_debug else "n"

        with open(self.defconfig_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        applied_changes = []
        new_lines = []
        found_keys = set()

        for line in lines:
            line_stripped = line.strip()
            matched_flag = None

            for flag in target_flags:
                if line_stripped.startswith(f"{flag}=") or line_stripped == f"# {flag} is not set":
                    matched_flag = flag
                    break

            if matched_flag:
                found_keys.add(matched_flag)
                desired_val = target_flags[matched_flag]
                if desired_val == "y":
                    new_line = f"{matched_flag}=y\n"
                elif desired_val == "n":
                    new_line = f"# {matched_flag} is not set\n"
                else:
                    new_line = f"{matched_flag}={desired_val}\n"

                new_lines.append(new_line)
                applied_changes.append(f"Updated {matched_flag} -> {desired_val}")
            else:
                new_lines.append(line)

        # Append any flags not already present in the original defconfig
        missing_flags = set(target_flags.keys()) - found_keys
        if missing_flags:
            new_lines.append("\n# Added by OmniKSU Automated Builder\n")
            for flag in sorted(missing_flags):
                desired_val = target_flags[flag]
                if desired_val == "y":
                    new_lines.append(f"{flag}=y\n")
                elif desired_val == "n":
                    new_lines.append(f"# {flag} is not set\n")
                else:
                    new_lines.append(f"{flag}={desired_val}\n")
                applied_changes.append(f"Appended {flag} -> {desired_val}")

        with open(self.defconfig_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, applied_changes
