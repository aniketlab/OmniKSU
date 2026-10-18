# OmniKSU ⚡
> **Automated Universal KernelSU-Next & BakaSU Build System for Non-GKI Android Devices & Stock OEM ROMs.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Root: BakaSU & KernelSU-Next](https://img.shields.io/badge/Root-BakaSU%20%7C%20KernelSU--Next-orange.svg)](https://github.com/Baka-SU/BakaSU)
[![Platform: Linux 3.18 to 4.19](https://img.shields.io/badge/Kernels-3.18%20%7C%204.4%20%7C%204.9%20%7C%204.14-purple.svg)](https://github.com/aniketlab/OmniKSU)

---

## 📌 Problem Statement

Millions of legacy Android devices (powered by Snapdragon 636, 660, 845, Helio G90T, Exynos 9611, running Linux kernels **3.18, 4.4, 4.9, 4.14**) are restricted from modern kernel-level root solutions like **KernelSU-Next** and **BakaSU** on their **Stock OEM ROMs** (MIUI, OxygenOS, RealmeUI, OneUI).

Until now, getting BakaSU / KernelSU on these devices required:
1. High-spec Linux environments with gigabytes of cross-compilation toolchains.
2. Fragile git-patch files (`git apply`) that break whenever an OEM modifies a single line of whitespace.
3. Complex manual hooking of filesystem syscalls (`fs/exec.c`, `fs/stat.c`, `fs/open.c`).
4. Bootloop and Wi-Fi crashes caused by kernel module vermagic mismatches on stock firmware.

**OmniKSU completely solves this by providing a fully automated, conflict-free pipeline.**

---

## 🛠️ Architecture & Features

```
┌────────────────────────────────────────────────────────┐
│                   OmniKSU Pipeline                     │
└────────────────────────────────────────────────────────┘
                           │
       [1] Kernel Intelligence & Version Detector
               (Auto-detects 4.4, 4.9, 4.14 etc.)
                           │
       [2] Root Engine Integrator
               (Pulls BakaSU / KernelSU-Next into drivers/)
                           │
       [3] Smart Syntax-Aware Patcher
               (Safe regex-based hook injection - No git conflicts!)
                           │
       [4] Defconfig Auto-Tuning Engine
               (Injects CONFIG_KSU, OVERLAY_FS, disables sig-panics)
                           │
       [5] Dynamic Toolchain Manager
               (Maps kernel to AOSP GCC 4.9 or Proton Clang)
                           │
       [6] AnyKernel3 Stock ROM Packager
               (Creates direct flashable ZIP for TWRP/OrangeFox)
```

### Key Highlights:
- **Smart Patcher (No Broken Git Diffs):** Instead of unified diffs that easily fail, OmniKSU parses C code syntax and injects hooks safely into `fs/exec.c`, `fs/stat.c`, `fs/open.c`, `fs/read_write.c`, and `kernel/reboot.c`.
- **Zero Local Hardware Requirement:** Run the complete compilation via free GitHub Actions cloud runners (Ubuntu 22.04 with 16GB RAM).
- **Stock ROM Preservation:** Output kernels are packaged into tailored **AnyKernel3** flashable archives, preserving original ramdisks and OEM Wi-Fi/audio drivers.

---

## 📱 Verified Device Support Matrix

| Codename | Device | SoC | Kernel | Stock ROM | Root Engine | Hook Mode |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`whyred`** | Redmi Note 5 Pro / AI | SD636 | Linux 4.4 | MIUI 12 (Android 9 Pie) | BakaSU | Manual Hook |
| **`enchilada`** | OnePlus 6 | SD845 | Linux 4.9 | OxygenOS 11 (Android 11) | BakaSU | Manual Hook |
| *(Generic)* | Any Non-GKI device | ARM64 | 3.18 - 4.19 | Any Stock / Custom ROM | BakaSU / KSU-Next | Auto-detected |

---

## 🚀 Quick Start (CLI Usage)

```bash
# Clone OmniKSU
git clone https://github.com/aniketlab/OmniKSU.git
cd OmniKSU

# 1. Detect kernel version and optimal root strategy
python omniksu.py detect /path/to/kernel_source

# 2. Integrate BakaSU into kernel drivers/
python omniksu.py integrate /path/to/kernel_source --engine bakasu

# 3. Apply smart manual hooks cleanly
python omniksu.py patch /path/to/kernel_source

# 4. Tune device defconfig with KSU flags
python omniksu.py defconfig /path/to/kernel_source/arch/arm64/configs/whyred-perf_defconfig

# 5. Package output kernel into flashable AnyKernel3 zip
python omniksu.py package /path/to/out/Image.gz-dtb --device whyred --out OmniKSU-Whyred-Flashable.zip
```

---

## ☁️ 1-Click Cloud Compilation via GitHub Actions

1. Fork or push this repository to GitHub.
2. Go to the **Actions** tab.
3. Select **"OmniKSU: Build Redmi Note 5 Pro (Whyred)"** or **"OmniKSU: Generic Universal Kernel Builder"**.
4. Click **Run workflow**.
5. Once complete (typically 8–15 minutes), download the ready-to-flash zip from the **Artifacts** section!

---

## ⚖️ License & Attribution

- **OmniKSU Engine:** Licensed under [GNU General Public License v3.0 (GPLv3)](LICENSE).
- **BakaSU:** Developed by the [Baka-SU Team](https://github.com/Baka-SU/BakaSU).
- **KernelSU-Next:** Developed by the [KernelSU-Next Team](https://github.com/KernelSU-Next/KernelSU-Next).
- **AnyKernel3:** Developed by [osm0sis](https://github.com/osm0sis/AnyKernel3).

---
*Maintained with ❤️ by [Aniket Sharma](https://github.com/aniketlab)*
