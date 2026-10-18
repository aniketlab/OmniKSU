import os
from pathlib import Path
from typing import Dict, Any, List, Optional

class ToolchainManager:
    """
    Manages compiler toolchains, download definitions, environment variables,
    and make command arguments for target kernel builds.
    """

    TOOLCHAIN_PRESETS = {
        "gcc-4.9": {
            "name": "Google AOSP GCC 4.9 (64-bit + 32-bit)",
            "repo_64": "https://android.googlesource.com/platform/prebuilts/gcc/linux-x86/aarch64/aarch64-linux-android-4.9",
            "branch_64": "pie-release",
            "repo_32": "https://android.googlesource.com/platform/prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9",
            "branch_32": "pie-release",
            "type": "gcc",
            "cc": "",
            "cross_compile": "aarch64-linux-android-",
            "cross_compile_arm32": "arm-linux-androideabi-",
            "clang_triple": ""
        },
        "proton-clang": {
            "name": "Proton Clang (LLVM 13 / Clang)",
            "repo": "https://github.com/kdrag0n/proton-clang.git",
            "branch": "master",
            "type": "clang",
            "cc": "clang",
            "cross_compile": "aarch64-linux-gnu-",
            "cross_compile_arm32": "arm-linux-gnueabi-",
            "clang_triple": "aarch64-linux-gnu-"
        },
        "clang-11": {
            "name": "AOSP Clang 11 (r383902)",
            "repo": "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86",
            "branch": "android11-release",
            "type": "clang",
            "cc": "clang",
            "cross_compile": "aarch64-linux-android-",
            "cross_compile_arm32": "arm-linux-androideabi-",
            "clang_triple": "aarch64-linux-gnu-"
        }
    }

    def __init__(self, preset_name: str = "gcc-4.9"):
        preset_name = preset_name.lower()
        if preset_name not in self.TOOLCHAIN_PRESETS:
            preset_name = "gcc-4.9"
        self.preset = self.TOOLCHAIN_PRESETS[preset_name]
        self.preset_name = preset_name

    def get_make_args(self, arch: str = "arm64", out_dir: Optional[str] = None) -> List[str]:
        """
        Builds the argument list for invoking 'make' with this toolchain.
        """
        args = [
            f"ARCH={arch}",
            f"SUBARCH={arch}"
        ]

        if out_dir:
            args.append(f"O={out_dir}")

        if self.preset["type"] == "clang":
            args.append("CC=clang")
            if self.preset["clang_triple"]:
                args.append(f"CLANG_TRIPLE={self.preset['clang_triple']}")

        if self.preset["cross_compile"]:
            args.append(f"CROSS_COMPILE={self.preset['cross_compile']}")

        if self.preset["cross_compile_arm32"]:
            args.append(f"CROSS_COMPILE_ARM32={self.preset['cross_compile_arm32']}")

        return args
