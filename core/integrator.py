import os
import subprocess
from pathlib import Path
from typing import Tuple, Optional

class RootIntegrator:
    """
    Manages fetching and wiring KernelSU-Next or BakaSU directly into
    the kernel drivers build tree.
    """

    REPOS = {
        "bakasu": {
            "url": "https://github.com/Baka-SU/BakaSU.git",
            "branch": "main",
            "name": "BakaSU"
        },
        "kernelsu-next": {
            "url": "https://github.com/KernelSU-Next/KernelSU-Next.git",
            "branch": "next",
            "name": "KernelSU-Next"
        }
    }

    def __init__(self, kernel_root: Path):
        self.kernel_root = Path(kernel_root).resolve()
        self.drivers_dir = self.kernel_root / "drivers"
        self.ksu_dir = self.drivers_dir / "kernelsu"

    def is_already_wired(self) -> bool:
        """Checks if drivers/Makefile and drivers/Kconfig already include KSU."""
        drivers_makefile = self.drivers_dir / "Makefile"
        if not drivers_makefile.is_file():
            return False
        with open(drivers_makefile, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return "CONFIG_KSU" in content

    def wire_drivers(self) -> Tuple[bool, str]:
        """
        Injects obj-$(CONFIG_KSU) += kernelsu/ into drivers/Makefile
        and source "drivers/kernelsu/Kconfig" into drivers/Kconfig.
        """
        drivers_makefile = self.drivers_dir / "Makefile"
        drivers_kconfig = self.drivers_dir / "Kconfig"

        if not drivers_makefile.is_file():
            return False, f"drivers/Makefile not found in {self.drivers_dir}"
        if not drivers_kconfig.is_file():
            return False, f"drivers/Kconfig not found in {self.drivers_dir}"

        # 1. Update drivers/Makefile
        with open(drivers_makefile, "r", encoding="utf-8", errors="ignore") as f:
            makefile_content = f.read()

        if "obj-$(CONFIG_KSU)" not in makefile_content:
            with open(drivers_makefile, "a", encoding="utf-8") as f:
                f.write("\n# Added by OmniKSU\nobj-$(CONFIG_KSU) += kernelsu/\n")

        # 2. Update drivers/Kconfig
        with open(drivers_kconfig, "r", encoding="utf-8", errors="ignore") as f:
            kconfig_content = f.read()

        if 'source "drivers/kernelsu/Kconfig"' not in kconfig_content:
            # Insert right before 'endmenu' at the end of file
            if "endmenu" in kconfig_content:
                last_endmenu_idx = kconfig_content.rfind("endmenu")
                kconfig_content = (
                    kconfig_content[:last_endmenu_idx] +
                    '\nsource "drivers/kernelsu/Kconfig"\n\n' +
                    kconfig_content[last_endmenu_idx:]
                )
                with open(drivers_kconfig, "w", encoding="utf-8") as f:
                    f.write(kconfig_content)
            else:
                with open(drivers_kconfig, "a", encoding="utf-8") as f:
                    f.write('\nsource "drivers/kernelsu/Kconfig"\n')

        return True, "Successfully wired drivers/Makefile and drivers/Kconfig"

    def fetch_source(self, target: str = "bakasu", depth: int = 1) -> Tuple[bool, str]:
        """
        Clones the root engine repository into drivers/kernelsu.
        """
        target = target.lower()
        if target not in self.REPOS:
            return False, f"Unknown target '{target}'. Choose from: {list(self.REPOS.keys())}"

        repo_info = self.REPOS[target]
        repo_url = repo_info["url"]
        branch = repo_info["branch"]

        if self.ksu_dir.exists():
            return True, f"Target directory {self.ksu_dir} already exists."

        cmd = [
            "git", "clone",
            f"--depth={depth}",
            "-b", branch,
            repo_url,
            str(self.ksu_dir)
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, f"Successfully cloned {repo_info['name']} ({branch}) into drivers/kernelsu"
        except subprocess.CalledProcessError as e:
            return False, f"Failed to clone {repo_url}: {e.stderr}"

    def integrate(self, target: str = "bakasu") -> Tuple[bool, str]:
        """
        Full integration flow: clones repo and wires Makefiles.
        """
        fetch_ok, fetch_msg = self.fetch_source(target)
        if not fetch_ok:
            return False, fetch_msg

        wire_ok, wire_msg = self.wire_drivers()
        if not wire_ok:
            return False, wire_msg

        return True, f"Integration of {target} completed successfully."
