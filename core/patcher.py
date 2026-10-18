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

        # Insert hook call inside do_execveat_common after variable declarations (ISO C90 compliant)
        pattern = r"(static\s+int\s+do_execveat_common\s*\([^{]+\{.*?\n\s*int\s+retval;\s*)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            fallback_pattern = r"(static\s+int\s+do_execveat_common\s*\([^{]+\{\s*)"
            match_fb = re.search(fallback_pattern, content)
            if match_fb:
                pos = match_fb.end()
                content = content[:pos] + call_hook + content[pos:]
            else:
                return False, "Could not locate do_execveat_common in fs/exec.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "fs/exec.c successfully patched."

    def patch_stat_c(self) -> Tuple[bool, str]:
        """
        Patches fs/stat.c for vfs_statx / vfs_fstatat / newfstat / fstat64 hooking.
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
            "extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);\n"
            "#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)\n"
            "extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);\n"
            "#endif\n"
            "#endif\n"
        )

        stat_call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_stat(&dfd, &filename, &flag);\n"
            "#endif\n"
        )

        # 1. Insert header declarations
        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        # 2. Hook vfs_fstatat or newfstatat after declarations (ISO C90 compliant)
        pattern = r"(int\s+vfs_fstatat\s*\([^{]+\{.*?\n\s*unsigned\s+int\s+lookup_flags\s*=\s*0;\s*)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            pos = match.end()
            content = content[:pos] + stat_call_hook + content[pos:]
        else:
            fallback_pattern = r"(int\s+vfs_fstatat\s*\([^{]+\{\s*)"
            match_fb = re.search(fallback_pattern, content)
            if match_fb:
                pos = match_fb.end()
                content = content[:pos] + stat_call_hook + content[pos:]
            else:
                pattern_syscall = r"(SYSCALL_DEFINE4\s*\(\s*newfstatat[^{]+\{\s*)"
                s_match = re.search(pattern_syscall, content)
                if s_match:
                    pos = s_match.end()
                    content = content[:pos] + stat_call_hook + content[pos:]
                else:
                    return False, "Could not locate vfs_fstatat or newfstatat in fs/stat.c"

        # 3. Hook newfstat (ksu_handle_newfstat_ret)
        newfstat_pattern = r"(SYSCALL_DEFINE2\s*\(\s*newfstat\b[^{]+\{.*?)(\n\s*return\s+error;)"
        newfstat_replacement = (
            r"\1"
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_newfstat_ret(&fd, &statbuf);\n"
            "#endif"
            r"\2"
        )
        content, n_subs = re.subn(newfstat_pattern, newfstat_replacement, content, count=1, flags=re.DOTALL)

        # 4. Hook fstat64 (ksu_handle_fstat64_ret)
        fstat64_pattern = r"(SYSCALL_DEFINE2\s*\(\s*fstat64\b[^{]+\{.*?)(\n\s*return\s+error;)"
        fstat64_replacement = (
            r"\1"
            "\n#if defined(CONFIG_KSU_MANUAL_HOOK) && (defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64))\n"
            "\tksu_handle_fstat64_ret(&fd, &statbuf);\n"
            "#endif"
            r"\2"
        )
        content, f_subs = re.subn(fstat64_pattern, fstat64_replacement, content, count=1, flags=re.DOTALL)

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

        # Target SYSCALL_DEFINE3(faccessat) after declarations (ISO C90 compliant)
        pattern = r"(SYSCALL_DEFINE3\s*\(\s*faccessat[^{]+\{.*?\n\s*struct\s+inode\s*\*inode;\s*)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            fallback_pattern = r"(SYSCALL_DEFINE3\s*\(\s*faccessat[^{]+\{\s*)"
            match_fb = re.search(fallback_pattern, content)
            if match_fb:
                pos = match_fb.end()
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

        # Target SYSCALL_DEFINE4(reboot) after declarations (ISO C90 compliant)
        pattern = r"(SYSCALL_DEFINE4\s*\(\s*reboot[^{]+\{.*?\n\s*int\s+ret\s*=\s*0;\s*)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            pos = match.end()
            content = content[:pos] + call_hook + content[pos:]
        else:
            fallback_pattern = r"(SYSCALL_DEFINE4\s*\(\s*reboot[^{]+\{\s*)"
            match_fb = re.search(fallback_pattern, content)
            if match_fb:
                pos = match_fb.end()
                content = content[:pos] + call_hook + content[pos:]
            else:
                return False, "Could not locate reboot syscall in kernel/reboot.c"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "kernel/reboot.c successfully patched."

    def fix_dtc_yylloc(self) -> List[str]:
        """
        Fixes multiple definition of 'yylloc' on GCC 10+ host compilers.
        """
        fixed = []
        target_files = [
            self.kernel_root / "scripts" / "dtc" / "dtc-lexer.lex.c_shipped",
            self.kernel_root / "scripts" / "dtc" / "dtc-lexer.l",
        ]
        for tf in target_files:
            if not tf.is_file():
                continue
            with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                c = f.read()
            if "YYLTYPE yylloc;" in c and "extern YYLTYPE yylloc;" not in c:
                c = c.replace("YYLTYPE yylloc;", "extern YYLTYPE yylloc;")
                with open(tf, "w", encoding="utf-8") as f:
                    f.write(c)
                fixed.append(tf.name)
        return fixed

    def sanitize_makefiles(self) -> List[str]:
        """
        Removes -Werror and adds -fcommon for host compilers to prevent
        OEM compilation failures on modern Linux build systems.
        """
        cleaned = []
        target_makefiles = [
            self.kernel_root / "Makefile",
            self.kernel_root / "arch" / "arm64" / "Makefile",
        ]
        for mf in target_makefiles:
            if not mf.is_file():
                continue
            with open(mf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if "-Werror" in content:
                # Replace standalone -Werror (e.g. -Werror followed by space, newline, or quotes)
                new_content = re.sub(r"-Werror(?=[\s\n\"\']|$)", "-Wno-error", content)
                # Convert any -Werror-implicit-function-declaration to valid GCC flag -Wno-error=implicit-function-declaration
                new_content = re.sub(
                    r"-W(?:no-)?error-implicit-function-declaration",
                    "-Wno-error=implicit-function-declaration",
                    new_content
                )
                if new_content != content:
                    with open(mf, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    cleaned.append(f"Sanitized -Werror in {mf.name}")

        root_makefile = self.kernel_root / "Makefile"
        if root_makefile.is_file():
            with open(root_makefile, "r", encoding="utf-8", errors="ignore") as f:
                rm_content = f.read()

            # Neutralize Qualcomm gcc-wrapper in root Makefile
            rm_content = re.sub(
                r"CC\s*=\s*\$\(srctree\)/scripts/gcc-wrapper\.py\s+\$\(REAL_CC\)",
                "CC = $(REAL_CC)",
                rm_content
            )

            if "HOSTCFLAGS += -fcommon" not in rm_content:
                rm_content += "\n# Added by OmniKSU for GCC 10+ host compatibility and warning tolerance\n"
                rm_content += "HOSTCFLAGS += -fcommon\nHOSTCXXFLAGS += -fcommon\n"
                rm_content += "KBUILD_CFLAGS += -Wno-declaration-after-statement\n"
                with open(root_makefile, "w", encoding="utf-8") as f:
                    f.write(rm_content)
                cleaned.append("Tuned root Makefile (disabled gcc-wrapper, added -fcommon & -Wno-declaration-after-statement)")

        # Also neutralize scripts/gcc-wrapper.py directly if present
        wrapper_py = self.kernel_root / "scripts" / "gcc-wrapper.py"
        if wrapper_py.is_file():
            with open(wrapper_py, "r", encoding="utf-8", errors="ignore") as f:
                wp = f.read()
            if "sys.exit(1)" in wp:
                wp = wp.replace("sys.exit(1)", "pass")
                with open(wrapper_py, "w", encoding="utf-8") as f:
                    f.write(wp)
                cleaned.append("Neutralized scripts/gcc-wrapper.py warning exit")

        return cleaned

    def apply_all_manual_hooks(self) -> Dict[str, Tuple[bool, str]]:
        """
        Executes all manual hook patches across the kernel tree and sanitizes Makefiles.
        """
        results = {}
        results["fs/exec.c"] = self.patch_exec_c()
        results["fs/stat.c"] = self.patch_stat_c()
        results["fs/open.c"] = self.patch_open_c()
        results["kernel/reboot.c"] = self.patch_reboot_c()

        # Fix GCC 10+ host dtc yylloc issue
        dtc_fixed = self.fix_dtc_yylloc()
        if dtc_fixed:
            results["dtc"] = (True, f"Fixed yylloc in {', '.join(dtc_fixed)}")

        # Sanitize Makefiles to prevent fatal -Werror warnings and host compiler errors
        sanitized = self.sanitize_makefiles()
        results["makefiles"] = (True, f"Sanitized: {', '.join(sanitized) if sanitized else 'Clean'}")

        return results
