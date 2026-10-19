import os
import re
import shutil
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
            "branch": "legacy",
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
        Clones the root engine repository and populates drivers/kernelsu
        with the driver source files (from the repo's kernel/ directory).
        """
        target = target.lower()
        if target not in self.REPOS:
            return False, f"Unknown target '{target}'. Choose from: {list(self.REPOS.keys())}"

        repo_info = self.REPOS[target]
        repo_url = repo_info["url"]
        branch = repo_info["branch"]

        if self.ksu_dir.exists() and (self.ksu_dir / "Kconfig").is_file():
            return True, f"Target directory {self.ksu_dir} is already populated."

        staging_dir = self.kernel_root / ".ksu_staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

        cmd = [
            "git", "clone",
            f"--depth={depth}",
            "-b", branch,
            repo_url,
            str(staging_dir)
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Root engine sources (BakaSU, KSU-Next) place driver code inside 'kernel/'
            kernel_sub = staging_dir / "kernel"
            if self.ksu_dir.exists():
                shutil.rmtree(self.ksu_dir, ignore_errors=True)
            self.ksu_dir.mkdir(parents=True, exist_ok=True)

            if kernel_sub.is_dir():
                for item in kernel_sub.iterdir():
                    dest = self.ksu_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
            else:
                for item in staging_dir.iterdir():
                    if item.name == ".git":
                        continue
                    dest = self.ksu_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)

            # Preserve git metadata so version macros (KSU_COMMIT_SHA, KSU_TAG_NAME) work
            git_sub = staging_dir / ".git"
            if git_sub.is_dir():
                shutil.copytree(git_sub, self.ksu_dir / ".git", dirs_exist_ok=True)

            # Clean up staging
            shutil.rmtree(staging_dir, ignore_errors=True)
            return True, f"Successfully integrated {repo_info['name']} ({branch}) into drivers/kernelsu"
        except subprocess.CalledProcessError as e:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return False, f"Failed to clone {repo_url}: {e.stderr}"

    def patch_kbuild_safety(self) -> None:
        """
        Bypasses strict submodule/path checks in BakaSU Kbuild so that
        in-tree compilation succeeds without requiring git submodules.
        """
        kbuild_file = self.ksu_dir / "Kbuild"
        if not kbuild_file.is_file():
            return

        with open(kbuild_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Force LOCAL_GIT_EXISTS := 1
        content = re.sub(
            r"LOCAL_GIT_EXISTS\s*:=\s*\$\(shell[^\)]+\)",
            "LOCAL_GIT_EXISTS := 1",
            content
        )

        # Fallback for rev-list count if git fails
        content = re.sub(
            r"KSU_LOCAL_VERSION\s*:=\s*\$\(shell\s+cd\s+\$\(KSU_SRC\);\s+\$\(GIT_BIN\)\s+rev-list\s+--count\s+HEAD\)",
            "KSU_LOCAL_VERSION := $(shell cd $(KSU_SRC); $(GIT_BIN) rev-list --count HEAD 2>/dev/null || echo 100)",
            content
        )

        with open(kbuild_file, "w", encoding="utf-8") as f:
            f.write(content)

    def patch_kernelsu_compat(self) -> None:
        """
        Fixes legacy kernel (Linux < 4.19) compatibility issues in KernelSU-Next:
        1. In drivers/kernelsu/selinux/rules.c: wraps unguarded selinux_state.ss
           reference with #if defined(KSU_COMPAT_USE_SELINUX_STATE).
        2. In drivers/kernelsu/runtime/ksud_integration.c: passes &fd instead of raw AT_FDCWD.
        """
        rules_c = self.ksu_dir / "selinux" / "rules.c"
        if rules_c.is_file():
            with open(rules_c, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            pattern = r"u32\s+seqno\s*=\s*selinux_state\.ss\s*\?\s*\+\+selinux_state\.ss->latest_granting\s*:\s*1\s*;"
            if re.search(pattern, content):
                replacement = (
                    "#if defined(KSU_COMPAT_USE_SELINUX_STATE)\n"
                    "\tu32 seqno = selinux_state.ss ? ++selinux_state.ss->latest_granting : 1;\n"
                    "#else\n"
                    "\tu32 seqno = 1;\n"
                    "#endif"
                )
                content = re.sub(pattern, replacement, content)
                with open(rules_c, "w", encoding="utf-8") as f:
                    f.write(content)

        ksud_c = self.ksu_dir / "runtime" / "ksud_integration.c"
        if ksud_c.is_file():
            with open(ksud_c, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            pattern = r"return\s+ksu_handle_execveat_ksud\s*\(\s*AT_FDCWD\s*,\s*&filename_p\s*,\s*argv\s*,\s*NULL\s*,\s*NULL\s*\)\s*;"
            if re.search(pattern, content):
                replacement = (
                    "int fd = AT_FDCWD;\n"
                    "\treturn ksu_handle_execveat_ksud(&fd, &filename_p, argv, NULL, NULL);"
                )
                content = re.sub(pattern, replacement, content)
                with open(ksud_c, "w", encoding="utf-8") as f:
                    f.write(content)

    def integrate(self, target: str = "bakasu") -> Tuple[bool, str]:
        """
        Full integration flow: clones repo, wires Makefiles, and patches Kbuild.
        """
        fetch_ok, fetch_msg = self.fetch_source(target)
        if not fetch_ok:
            return False, fetch_msg

        wire_ok, wire_msg = self.wire_drivers()
        if not wire_ok:
            return False, wire_msg

        self.patch_kbuild_safety()
        self.patch_kernelsu_compat()

        return True, f"Integration of {target} completed successfully."
