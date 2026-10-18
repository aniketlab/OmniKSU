#!/usr/bin/env python3
"""
OmniKSU - Automated Universal KernelSU-Next / BakaSU Build System
Author: Aniket Sharma <https://github.com/aniketlab>
License: GPLv3
"""

import sys
import json
import argparse
from pathlib import Path

from core.detector import KernelDetector
from core.patcher import SmartPatcher
from core.defconfig import DefconfigPatcher
from core.integrator import RootIntegrator
from core.toolchain import ToolchainManager
from core.packager import AnyKernelPackager

CONFIG_FILE = Path(__file__).parent / "config" / "devices.json"

def load_devices():
    if not CONFIG_FILE.is_file():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("devices", {})

def cmd_detect(args):
    kernel_path = Path(args.kernel_path)
    detector = KernelDetector(kernel_path)

    if not detector.is_valid_kernel_tree():
        print(f"[!] Error: {kernel_path} is not a valid Linux kernel source tree.")
        sys.exit(1)

    version_info = detector.detect_version()
    strategy = detector.get_recommended_strategy(version_info)

    print("========================================")
    print(f"[*] Kernel Source Detected: {kernel_path.name}")
    print(f"[*] Full Version:          {version_info['full_version']}")
    print(f"[*] Kernel Family:         {version_info['family']}")
    print("----------------------------------------")
    print(f"[*] Recommended Engine:    {strategy['root_engine'].upper()}")
    print(f"[*] Hooking Mode:          {strategy['hook_mode'].upper()}")
    print(f"[*] Target Toolchain:      {strategy['toolchain']}")
    print(f"[*] Rationale:             {strategy['reason']}")
    print("========================================")

def cmd_patch(args):
    kernel_path = Path(args.kernel_path)
    print(f"[*] Running OmniKSU Smart Patcher on {kernel_path}...")

    patcher = SmartPatcher(kernel_path)
    results = patcher.apply_all_manual_hooks()

    all_success = True
    print("\n--- Patching Summary ---")
    for file_rel, (ok, msg) in results.items():
        status = "[OK] SUCCESS" if ok else "[X] FAILED "
        print(f"{status} | {file_rel:18} | {msg}")
        if not ok:
            all_success = False

    if all_success:
        print("\n[OK] All manual hooks cleanly injected without git conflicts!")
    else:
        print("\n[!] Warning: One or more hooks encountered an error.")
        sys.exit(1)

def cmd_defconfig(args):
    defconfig_path = Path(args.defconfig_path)
    patcher = DefconfigPatcher(defconfig_path)

    ok, changes = patcher.patch(manual_hook=not args.no_manual_hook, enable_debug=args.debug)
    if not ok:
        print(f"[!] Error: {changes[0]}")
        sys.exit(1)

    print(f"[OK] Defconfig successfully updated at {defconfig_path.name}:")
    for change in changes:
        print(f"    - {change}")

def cmd_integrate(args):
    kernel_path = Path(args.kernel_path)
    integrator = RootIntegrator(kernel_path)

    print(f"[*] Integrating {args.engine.upper()} into {kernel_path}...")
    ok, msg = integrator.integrate(target=args.engine)
    if ok:
        print(f"[OK] {msg}")
    else:
        print(f"[!] Failed: {msg}")
        sys.exit(1)

def cmd_device(args):
    devices = load_devices()
    codename = args.codename.lower()

    if codename == "list":
        print("\n=== Supported Verified Devices ===")
        for code, dev in devices.items():
            print(f"- {code:12} : {dev['brand']} {dev['name']} ({dev['kernel_version_family']} | {dev['tested_stock_os']})")
        return

    if codename not in devices:
        print(f"[!] Device '{codename}' not found in database. Use 'omniksu device list'.")
        sys.exit(1)

    dev = devices[codename]
    print(f"\n=== Profile: {dev['brand']} {dev['name']} ({codename}) ===")
    for k, v in dev.items():
        print(f"  {k:22}: {v}")

def cmd_package(args):
    packager = AnyKernelPackager(workspace_dir=Path("."))
    print("[*] Setting up AnyKernel3 template...")
    ok, msg = packager.setup_anykernel_template()
    if not ok:
        print(f"[!] {msg}")
        sys.exit(1)

    devices = load_devices()
    dev_names = [args.device]
    if args.device in devices:
        dev_names = devices[args.device].get("anykernel_device_names", [args.device])

    packager.configure_anykernel(device_names=dev_names)

    kernel_img = Path(args.kernel_image)
    out_zip = Path(args.out)
    ok, msg = packager.build_zip(kernel_img, out_zip)
    if ok:
        print(f"[OK] {msg}")
    else:
        print(f"[!] {msg}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        prog="omniksu",
        description="OmniKSU: Automated Universal KernelSU-Next / BakaSU Build System for Stock ROMs"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect
    p_detect = subparsers.add_parser("detect", help="Detect kernel version and recommended strategy")
    p_detect.add_argument("kernel_path", help="Path to kernel source tree")
    p_detect.set_defaults(func=cmd_detect)

    # patch
    p_patch = subparsers.add_parser("patch", help="Apply smart manual hooks to kernel tree")
    p_patch.add_argument("kernel_path", help="Path to kernel source tree")
    p_patch.set_defaults(func=cmd_patch)

    # defconfig
    p_def = subparsers.add_parser("defconfig", help="Update kernel defconfig with KSU flags")
    p_def.add_argument("defconfig_path", help="Path to target defconfig file")
    p_def.add_argument("--no-manual-hook", action="store_true", help="Do not enable CONFIG_KSU_MANUAL_HOOK")
    p_def.add_argument("--debug", action="store_true", help="Enable CONFIG_KSU_DEBUG")
    p_def.set_defaults(func=cmd_defconfig)

    # integrate
    p_int = subparsers.add_parser("integrate", help="Clone and wire root engine into drivers/")
    p_int.add_argument("kernel_path", help="Path to kernel source tree")
    p_int.add_argument("--engine", choices=["bakasu", "kernelsu-next"], default="bakasu", help="Target root engine")
    p_int.set_defaults(func=cmd_integrate)

    # device
    p_dev = subparsers.add_parser("device", help="Query device profiles database")
    p_dev.add_argument("codename", help="Device codename or 'list'")
    p_dev.set_defaults(func=cmd_device)

    # package
    p_pkg = subparsers.add_parser("package", help="Package compiled kernel into AnyKernel3 zip")
    p_pkg.add_argument("kernel_image", help="Path to Image.gz-dtb or Image")
    p_pkg.add_argument("--device", required=True, help="Target device codename")
    p_pkg.add_argument("--out", required=True, help="Output flashable zip path")
    p_pkg.set_defaults(func=cmd_package)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
