import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

class AnyKernelPackager:
    """
    Automates packaging of compiled kernel binaries into safe, AnyKernel3-based
    flashable ZIPs for Stock OEM recoveries and custom recoveries.
    """

    ANYKERNEL3_REPO = "https://github.com/osm0sis/AnyKernel3.git"

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.ak3_dir = self.workspace_dir / "AnyKernel3"

    @staticmethod
    def _safe_rmtree(path: Path) -> None:
        if not path.exists():
            return
        import stat
        def _on_error(func, p, excinfo):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                pass
        shutil.rmtree(path, onerror=_on_error)

    def setup_anykernel_template(self, depth: int = 1) -> Tuple[bool, str]:
        """Clones or resets the clean AnyKernel3 template."""
        if self.ak3_dir.exists():
            self._safe_rmtree(self.ak3_dir)

        cmd = ["git", "clone", f"--depth={depth}", self.ANYKERNEL3_REPO, str(self.ak3_dir)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Remove git folder so it is clean
            git_folder = self.ak3_dir / ".git"
            if git_folder.exists():
                self._safe_rmtree(git_folder)
            return True, "AnyKernel3 template ready."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to clone AnyKernel3: {e.stderr}"

    def configure_anykernel(
        self,
        device_names: List[str],
        block_path: str = "boot",
        is_slot_device: bool = False,
        enable_device_check: bool = False
    ) -> Tuple[bool, str]:
        """
        Customizes anykernel.sh with device-specific metadata and universal boot partition settings.
        Disables strict device checks by default (do.devicecheck=0) so flashable zips work
        universally across all regional variants, custom ROMs, and recovery prop variations.
        """
        ak3_sh = self.ak3_dir / "anykernel.sh"
        if not ak3_sh.is_file():
            return False, "anykernel.sh not found."

        with open(ak3_sh, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Set kernel string
        content = re.sub(r"kernel\.string=[^\n]+", "kernel.string=OmniKSU BakaSU Kernel", content)

        # Disable strict devicecheck (0 = universal, skips recovery property abort)
        check_val = "1" if enable_device_check else "0"
        content = re.sub(r"do\.devicecheck=[0-1]", f"do.devicecheck={check_val}", content)

        # Set clean device names without semicolons (AnyKernel3 properties block is key=value)
        clean_names = [d.strip(";").strip() for d in device_names if d.strip(";").strip()]
        for i in range(1, 6):
            key = f"device.name{i}"
            val = clean_names[i - 1] if i <= len(clean_names) else ""
            content = re.sub(rf"{key}=[^\n]*", f"{key}={val}", content)

        # Set is_slot_device (case-insensitive)
        slot_val = "1" if is_slot_device else "0"
        content = re.sub(r"(?i)is_slot_device=[^;]+;", f"IS_SLOT_DEVICE={slot_val};", content)

        # Set BLOCK partition (case-insensitive, default 'boot' auto-detects on all Android devices)
        content = re.sub(r"(?i)block=[^;]+;", f"BLOCK={block_path};", content)

        # Remove sample Galaxy Nexus (tuna) specific ramdisk/fstab scripts between dump_boot and write_boot
        tuna_pattern = r"(dump_boot;\s*#?[^\n]*\n)(.*?)(\n\s*write_boot;)"
        content = re.sub(tuna_pattern, r"\1\nwrite_boot;", content, flags=re.DOTALL)

        with open(ak3_sh, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

        return True, "anykernel.sh configured successfully."

    def build_zip(self, kernel_image_path: Path, output_zip_path: Path) -> Tuple[bool, str]:
        """
        Copies the kernel image into AnyKernel3 and compresses everything into a flashable ZIP.
        Explicitly enforces UNIX POSIX permissions (0755 for executables/scripts, 0644 for regular files)
        and converts Windows CRLF line endings to UNIX LF so Android recoveries (TWRP/OrangeFox)
        do not fail with ERROR: 255 (EACCES / ENOENT).
        """
        import time

        kernel_image_path = Path(kernel_image_path).resolve()
        output_zip_path = Path(output_zip_path).resolve()

        if not kernel_image_path.is_file():
            return False, f"Kernel image not found: {kernel_image_path}"

        # Copy kernel image to AnyKernel3 directory
        # Retain original name (e.g. Image.gz-dtb or Image)
        dest_img = self.ak3_dir / kernel_image_path.name
        shutil.copy2(kernel_image_path, dest_img)

        # Ensure output directory exists
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        # Create zip archive
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.ak3_dir):
                # Write directory entries
                for d in dirs:
                    dir_full = Path(root) / d
                    rel_dir = dir_full.relative_to(self.ak3_dir)
                    dinfo = zipfile.ZipInfo(filename=rel_dir.as_posix() + "/")
                    dinfo.create_system = 3  # UNIX
                    dinfo.external_attr = 0o40755 << 16  # drwxr-xr-x
                    zipf.writestr(dinfo, b"")

                for file in files:
                    file_full = Path(root) / file
                    rel_path = file_full.relative_to(self.ak3_dir)
                    posix_name = rel_path.as_posix()

                    zinfo = zipfile.ZipInfo(filename=posix_name)
                    zinfo.create_system = 3  # UNIX origin so recoveries honor permissions
                    zinfo.compress_type = zipfile.ZIP_DEFLATED

                    try:
                        zinfo.date_time = time.localtime(file_full.stat().st_mtime)[:6]
                    except Exception:
                        zinfo.date_time = (2026, 1, 1, 0, 0, 0)

                    data = file_full.read_bytes()

                    # Executable determination
                    is_exec = (
                        posix_name.startswith("tools/") or
                        posix_name.endswith(".sh") or
                        "update-binary" in posix_name
                    )

                    # Fix Windows CRLF line endings for shell scripts and text files (skip ELF binaries)
                    if not data.startswith(b"\x7fELF"):
                        if is_exec or posix_name.endswith((".txt", ".md", ".json", ".prop")) or "updater-script" in posix_name:
                            data = data.replace(b"\r\n", b"\n")

                    if is_exec:
                        zinfo.external_attr = 0o100755 << 16  # -rwxr-xr-x
                    else:
                        zinfo.external_attr = 0o100644 << 16  # -rw-r--r--

                    zipf.writestr(zinfo, data)

        return True, f"Flashable zip generated: {output_zip_path}"
