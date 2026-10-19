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
            "int __attribute__((weak)) ksu_handle_post_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags, int *retval) { return 0; }\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n"
            "#endif\n"
        )

        post_call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);\n"
            "#endif\n"
        )

        # Insert header declarations near top after includes
        include_match = list(re.finditer(r"#include\s+<[^>]+>", content))
        if include_match:
            last_include_pos = include_match[-1].end()
            content = content[:last_include_pos] + "\n" + header_hook + content[last_include_pos:]
        else:
            content = header_hook + content

        # Insert pre-hook call inside do_execveat_common after variable declarations (ISO C90 compliant)
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

        # Insert post-hook call before return retval in do_execveat_common
        # Pattern 1: error/cleanup exit path (out_ret: putname(filename);)
        out_pattern = r"(out_ret:\s*putname\s*\(\s*filename\s*\)\s*;\s*)"
        match_out = re.search(out_pattern, content)
        if match_out:
            pos_out = match_out.end()
            content = content[:pos_out] + post_call_hook + content[pos_out:]

        # Pattern 2: success exit path (put_files_struct(displaced);)
        success_pattern = r"(\bput_files_struct\s*\(\s*displaced\s*\)\s*;\s*)"
        match_succ = re.search(success_pattern, content)
        if match_succ:
            pos_succ = match_succ.end()
            content = content[:pos_succ] + post_call_hook + content[pos_succ:]

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
            "extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n"
            "#endif\n"
        )

        call_hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n"
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

    def patch_module_c(self) -> Tuple[bool, str]:
        """
        Patches kernel/module.c to bypass strict vermagic and symbol CRC checks
        (module_layout mismatch) for stock OEM prebuilt vendor modules (e.g. WiFi).
        """
        file_path = self.kernel_dir / "module.c"
        if not file_path.is_file():
            return False, f"File not found: {file_path}"

        if self.is_file_already_patched(file_path):
            return True, "kernel/module.c is already patched."

        self.backup_file(file_path)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # 1. Bypass same_magic check so any vermagic differences are tolerated
        same_magic_pattern = r"(static\s+inline\s+int\s+same_magic\s*\([^{]+\{\s*)"
        match_sm = re.search(same_magic_pattern, content)
        if match_sm:
            pos = match_sm.end()
            content = content[:pos] + "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\treturn 1;\n#endif\n" + content[pos:]

        # 2. Bypass check_version check so module_layout and symbol CRC mismatches are ignored
        check_ver_pattern = r"(static\s+int\s+check_version\s*\([^{]+\{\s*)"
        match_cv = re.search(check_ver_pattern, content)
        if match_cv:
            pos = match_cv.end()
            content = content[:pos] + "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\treturn 1;\n#endif\n" + content[pos:]

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "kernel/module.c successfully patched (bypassed vermagic & CRC checks)."

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

    def patch_kernelsu_compat(self) -> List[str]:
        """
        Fixes legacy kernel (Linux < 4.19) compatibility issues in KernelSU-Next:
        1. In drivers/kernelsu/selinux/rules.c: wraps unguarded selinux_state.ss
           reference with #if defined(KSU_COMPAT_USE_SELINUX_STATE).
        2. In drivers/kernelsu/runtime/ksud_integration.c: passes &fd instead of raw AT_FDCWD.
        """
        fixed = []
        ksu_dir = self.kernel_root / "drivers" / "kernelsu"
        rules_c = ksu_dir / "selinux" / "rules.c"
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
                fixed.append("selinux/rules.c (selinux_state guard for < 4.19)")

        ksud_c = ksu_dir / "runtime" / "ksud_integration.c"
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
                fixed.append("runtime/ksud_integration.c (fd pointer fix)")

        # 3. Fix compat/kernel_compat.h for missing kvcalloc, ALIGN_DOWN, in_compat_syscall, KSYM_NAME_LEN on < 4.12
        compat_h = ksu_dir / "compat" / "kernel_compat.h"
        if compat_h.is_file():
            with open(compat_h, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if "ksu_kvcalloc" not in content:
                content = re.sub(
                    r"(static\s+inline\s+void\s+\*ksu_kvmalloc[^\}]+\}\s*)",
                    r"\1\nstatic inline void *ksu_kvcalloc(size_t n, size_t size, gfp_t flags)\n{\n\treturn kcalloc(n, size, flags);\n}\n",
                    content
                )
                content = content.replace("#define kvfree ksu_kvfree", "#define kvcalloc ksu_kvcalloc\n#define kvfree ksu_kvfree")

            if "ALIGN_DOWN" not in content:
                content += (
                    "\n#ifndef ALIGN_DOWN\n"
                    "#define ALIGN_DOWN(x, a) __ALIGN_KERNEL((x) - ((a) - 1), (a))\n"
                    "#endif\n"
                )

            if "KSYM_NAME_LEN" not in content:
                content += (
                    "\n#ifndef KSYM_NAME_LEN\n"
                    "#include <linux/kallsyms.h>\n"
                    "#ifndef KSYM_NAME_LEN\n"
                    "#define KSYM_NAME_LEN 128\n"
                    "#endif\n"
                    "#endif\n"
                )

            if "in_compat_syscall" not in content:
                content += (
                    "\n#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 6, 0)\n"
                    "#ifndef in_compat_syscall\n"
                    "#define in_compat_syscall is_compat_task\n"
                    "#endif\n"
                    "#endif\n"
                )

            with open(compat_h, "w", encoding="utf-8") as f:
                f.write(content)
            fixed.append("compat/kernel_compat.h (kvcalloc, ALIGN_DOWN & compat backports)")

        # 4. Inject compat header into include/klog.h so all drivers/kernelsu files inherit it
        klog_h = ksu_dir / "include" / "klog.h"
        if klog_h.is_file():
            with open(klog_h, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if '"compat/kernel_compat.h"' not in content:
                content = '#include "compat/kernel_compat.h"\n' + content
                with open(klog_h, "w", encoding="utf-8") as f:
                    f.write(content)
                fixed.append("include/klog.h (injected kernel_compat.h)")

        # 5. Fix manager/apk_sign.c for kvmalloc
        apk_sign_c = ksu_dir / "manager" / "apk_sign.c"
        if apk_sign_c.is_file():
            with open(apk_sign_c, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if '"compat/kernel_compat.h"' not in content:
                content = '#include "compat/kernel_compat.h"\n' + content
                with open(apk_sign_c, "w", encoding="utf-8") as f:
                    f.write(content)
                fixed.append("manager/apk_sign.c (kvmalloc fix)")

        # 6. Fix feature/adb_root.c for ALIGN_DOWN
        adb_root_c = ksu_dir / "feature" / "adb_root.c"
        if adb_root_c.is_file():
            with open(adb_root_c, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if '"compat/kernel_compat.h"' not in content:
                content = '#include "compat/kernel_compat.h"\n' + content
                with open(adb_root_c, "w", encoding="utf-8") as f:
                    f.write(content)
                fixed.append("feature/adb_root.c (ALIGN_DOWN fix)")

        # 7. Fix supercall/dispatch.c for KSYM_NAME_LEN, kvcalloc and cmd.arg cast
        dispatch_c = ksu_dir / "supercall" / "dispatch.c"
        if dispatch_c.is_file():
            with open(dispatch_c, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if '"compat/kernel_compat.h"' not in content:
                content = '#include <linux/kallsyms.h>\n#include "compat/kernel_compat.h"\n' + content

            if "#ifndef KSYM_NAME_LEN" not in content:
                content = "#ifndef KSYM_NAME_LEN\n#define KSYM_NAME_LEN 128\n#endif\n" + content

            content = re.sub(
                r"strncpy_from_user\s*\(\s*mnt\s*,\s*cmd\.arg\s*,\s*sizeof\s*\(\s*mnt\s*\)\s*\)",
                "strncpy_from_user(mnt, (const char __user *)(uintptr_t)cmd.arg, sizeof(mnt))",
                content
            )

            with open(dispatch_c, "w", encoding="utf-8") as f:
                f.write(content)
            fixed.append("supercall/dispatch.c (KSYM_NAME_LEN & compat include)")

        return fixed

    def apply_all_manual_hooks(self) -> Dict[str, Tuple[bool, str]]:
        """
        Executes all manual hook patches across the kernel tree and sanitizes Makefiles.
        """
        results = {}
        results["fs/exec.c"] = self.patch_exec_c()
        results["fs/stat.c"] = self.patch_stat_c()
        results["fs/open.c"] = self.patch_open_c()
        results["kernel/reboot.c"] = self.patch_reboot_c()
        results["kernel/module.c"] = self.patch_module_c()

        # Fix KernelSU legacy compatibility if integrated
        compat_fixed = self.patch_kernelsu_compat()
        if compat_fixed:
            results["ksu_compat"] = (True, f"Fixed: {', '.join(compat_fixed)}")

        # Fix GCC 10+ host dtc yylloc issue
        dtc_fixed = self.fix_dtc_yylloc()
        if dtc_fixed:
            results["dtc"] = (True, f"Fixed yylloc in {', '.join(dtc_fixed)}")

        # Sanitize Makefiles to prevent fatal -Werror warnings and host compiler errors
        sanitized = self.sanitize_makefiles()
        results["makefiles"] = (True, f"Sanitized: {', '.join(sanitized) if sanitized else 'Clean'}")

        return results
