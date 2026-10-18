import os
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

    def setup_anykernel_template(self, depth: int = 1) -> Tuple[bool, str]:
        """Clones or resets the clean AnyKernel3 template."""
        if self.ak3_dir.exists():
            shutil.rmtree(self.ak3_dir)

        cmd = ["git", "clone", f"--depth={depth}", self.ANYKERNEL3_REPO, str(self.ak3_dir)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Remove git folder so it is clean
            git_folder = self.ak3_dir / ".git"
            if git_folder.exists():
                shutil.rmtree(git_folder)
            return True, "AnyKernel3 template ready."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to clone AnyKernel3: {e.stderr}"

    def configure_anykernel(
        self,
        device_names: List[str],
        block_path: str = "/dev/block/bootdevice/by-name/boot",
        is_slot_device: bool = False
    ) -> Tuple[bool, str]:
        """
        Customizes anykernel.sh with device-specific metadata.
        """
        ak3_sh = self.ak3_dir / "anykernel.sh"
        if not ak3_sh.is_file():
            return False, "anykernel.sh not found."

        with open(ak3_sh, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Set device names
        for i, dev in enumerate(device_names[:5], start=1):
            key = f"device.name{i}"
            content = content.replace(f"{key}=", f"{key}={dev}\n#")

        # Set is_slot_device
        slot_val = "1" if is_slot_device else "0"
        content = content.replace("is_slot_device=0;", f"is_slot_device={slot_val};")
        content = content.replace("is_slot_device=auto;", f"is_slot_device={slot_val};")

        # Set block path
        content = content.replace("block=/dev/block/bootdevice/by-name/boot;", f"block={block_path};")

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
