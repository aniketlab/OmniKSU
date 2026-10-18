import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional

class SmartPatcher:
    """
    Intelligent AST/Regex Hook Patcher for BakaSU and KernelSU-Next.
    Applies manual hooks directly into Linux kernel source files without
    fragile git-apply diff dependencies.
    """

    HOOK_GUARD = "CONFIG_KSU_MANUAL_HOOK"

    def __init__(self, kernel_root: Path):
        self.kernel_root = Path(kernel_root).resolve()
        self.fs_dir = self.kernel_root / "fs"
        self.kernel_dir = self.kernel_root / "kernel"

    def is_file_already_patched(self, file_path: Path) -> bool:
        """Checks if a file already contains KSU manual hooks."""
        if not file_path.is_file():
            return False
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return self.HOOK_GUARD in content

    def backup_file(self, file_path: Path) -> Path:
        """Creates a .bak copy of the target file if not already backed up."""
        bak_path = file_path.with_suffix(file_path.suffix + ".omniksu.bak")
        if not bak_path.exists():
            shutil.copy2(file_path, bak_path)
        return bak_path

    def patch_exec_c(self) -> Tuple[bool, str]:
        """
        Patches fs/exec.c for do_execveat_common or do_execve interception.
        """
        file_path = self.fs_dir / "exec.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "fs/exec.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # 1. Add Extern Declarations before do_execveat_common or first function
        header_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);\n"
            "extern int ksu_handle_execveat_sucompat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n"
            "\tksu_handle_execveat_sucompat(&fd, &filename, &argv, &envp, &flags);\n"
            "#endif\n"
        )

        # Insert header declarations near top after includes
        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        # Insert hook call inside do_execveat_common
        # Usually inside: static int do_execveat_common(...) { ...
        pattern = r"(static\s+int\s+do_execveat_common\s*\([^{]+\{\s*)"
        match = re.search(pattern, content)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            # Fallback for older 3.18/4.4 kernels using do_execve directly
            fallback_pattern = r"(int\s+do_execve\s*\([^{]+\{\s*)"
            fb_match = re.search(fallback_pattern, content)
            if fb_match:
                pos = fb_match.end()
                content = content[:pos] + call_hook + content[pos:]
            else:
                return False, "Could not locate do_execveat_common or do_execve in fs/exec.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "fs/exec.c successfully patched."

    def patch_stat_c(self) -> Tuple[bool, str]:
        """
        Patches fs/stat.c for vfs_statx / vfs_fstatat hooking.
        """
        file_path = self.fs_dir / "stat.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "fs/stat.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        header_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "extern int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_stat(&dfd, &filename, &flag);\n"
            "#endif\n"
        )

        # Insert header declarations
        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        # Look for vfs_fstatat or vfs_statx
        # In 4.4 / 4.9: int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat, int flag) {
        pattern = r"(int\s+vfs_fstatat\s*\([^{]+\{\s*)"
        match = re.search(pattern, content)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            # Check SYSCALL_DEFINE4(newfstatat
            pattern_syscall = r"(SYSCALL_DEFINE4\s*\(\s*newfstatat[^{]+\{\s*)"
            s_match = re.search(pattern_syscall, content)
            if s_match:
                pos = s_match.end()
                content = content[:pos] + call_hook + content[pos:]
            else:
                return False, "Could not locate vfs_fstatat or newfstatat in fs/stat.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "fs/stat.c successfully patched."

    def patch_open_c(self) -> Tuple[bool, str]:
        """
        Patches fs/open.c for faccessat hooking.
        """
        file_path = self.fs_dir / "open.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "fs/open.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        header_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *flags);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n"
            "#endif\n"
        )

        # Insert header
        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        # Target SYSCALL_DEFINE3(faccessat... or do_faccessat
        pattern = r"(SYSCALL_DEFINE3\s*\(\s*faccessat[^{]+\{\s*)"
        match = re.search(pattern, content)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            pattern2 = r"(long\s+do_faccessat[^{]+\{\s*)"
            match2 = re.search(pattern2, content)
            if match2:
                pos = match2.end()
                content = content[:pos] + call_hook + content[pos:]
            else:
                return False, "Could not locate faccessat in fs/open.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "fs/open.c successfully patched."

    def patch_read_write_c(self) -> Tuple[bool, str]:
        """
        Patches fs/read_write.c for vfs_read hooking.
        """
        file_path = self.fs_dir / "read_write.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "fs/read_write.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        header_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "extern int ksu_handle_vfs_read(struct file **file_ptr, char __user **buf_ptr, size_t *count_ptr, loff_t **pos);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_vfs_read(&file, &buf, &count, &pos);\n"
            "#endif\n"
        )

        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        pattern = r"(ssize_t\s+vfs_read\s*\([^{]+\{\s*)"
        match = re.search(pattern, content)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            return False, "Could not locate vfs_read in fs/read_write.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "fs/read_write.c successfully patched."

    def patch_reboot_c(self) -> Tuple[bool, str]:
        """
        Patches kernel/reboot.c for reboot command handling.
        """
        file_path = self.kernel_dir / "reboot.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "kernel/reboot.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        header_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user *arg);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_sys_reboot(magic1, magic2, cmd, arg);\n"
            "#endif\n"
        )

        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        pattern = r"(SYSCALL_DEFINE4\s*\(\s*reboot[^{]+\{\s*)"
        match = re.search(pattern, content)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            return False, "Could not locate reboot syscall in kernel/reboot.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "kernel/reboot.c successfully patched."

    def apply_all_manual_hooks(self) -> Dict[str, Tuple[bool, str]]:
        """
        Executes all manual hook patches across the kernel tree.
        """
        results = {}
        results["fs/exec.c"] = self.patch_exec_c()
        results["fs/stat.c"] = self.patch_stat_c()
        results["fs/open.c"] = self.patch_open_c()
        results["fs/read_write.c"] = self.patch_read_write_c()
        results["kernel/reboot.c"] = self.patch_reboot_c()
        return results
