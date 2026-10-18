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
        is_slot_device: bool = False
    ) -> Tuple[bool, str]:
        """
        Customizes anykernel.sh with device-specific metadata and universal boot partition settings.
        """
        ak3_sh = self.ak3_dir / "anykernel.sh"
        if not ak3_sh.is_file():
            return False, "anykernel.sh not found."

        with open(ak3_sh, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Set kernel string
        content = re.sub(r"kernel\.string=[^\n]+", "kernel.string=OmniKSU BakaSU Kernel", content)

        # Set device names
        for i, dev in enumerate(device_names[:5], start=1):
            key = f"device.name{i}"
            content = re.sub(rf"{key}=[^\n]*", f"{key}={dev};", content)

        # Clear remaining unused sample device names (maguro, toro, etc.)
        for j in range(len(device_names) + 1, 6):
            key = f"device.name{j}"
            content = re.sub(rf"{key}=[^\n]*", f"{key}=;", content)

        # Set is_slot_device (case-insensitive)
        slot_val = "1" if is_slot_device else "0"
        content = re.sub(r"(?i)is_slot_device=[^;]+;", f"IS_SLOT_DEVICE={slot_val};", content)

        # Set BLOCK partition (case-insensitive, default 'boot' auto-detects on all Android devices)
        content = re.sub(r"(?i)block=[^;]+;", f"BLOCK={block_path};", content)

        # Remove sample Galaxy Nexus (tuna) specific ramdisk/fstab scripts between dump_boot and write_boot
        tuna_pattern = r"(dump_boot;\s*#?[^\n]*\n)(.*?)(\n\s*write_boot;)"
        content = re.sub(tuna_pattern, r"\1\nwrite_boot;", content, flags=re.DOTALL)

        with open(ak3_sh, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "anykernel.sh configured successfully."

    def build_zip(self, kernel_image_path: Path, output_zip_path: Path) -> Tuple[bool, str]:
        """
        Copies the kernel image into AnyKernel3 and compresses everything into a flashable ZIP.
        """
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
            for root, _, files in os.walk(self.ak3_dir):
                for file in files:
                    file_full = Path(root) / file
                    rel_path = file_full.relative_to(self.ak3_dir)
                    zipf.write(file_full, arcname=str(rel_path))

        return True, f"Flashable zip generated: {output_zip_path}"
