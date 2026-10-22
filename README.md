# GR III Film Firmware Mods (Duccio edition)

**English** | [简体中文](README.zh-CN.md)

Custom film-simulation firmware tooling for the Ricoh GR III (fw 2.10): **Duccio's own film presets**
(Kodak Portra 400, Ektar 100, Vision3 5207, Vision3 5219) + a **native in-camera grain engine** + a **local web
build tool**, producing flashable firmware fully offline.

## What this project is

Built on top of the GR III firmware reverse-engineering research in
[idontknownihil/gr3-film-mods](https://github.com/idontknownihil/gr3-film-mods) (MIT). On top of that
base, three components are original work of this fork:

### 1. Native in-camera grain engine (original; not present upstream)
- All film slots reuse the camera's built-in "Grain effect" menu (Off / Low / Mid / High)
- Reverse-engineered the three grain parameter types (level enum / auxiliary / strength) and writes
  per-film defaults for each
- Fixes across the menu list, gate dispatch and RTOS space allocation; verified by offline emulation

### 2. Duccio film line (original data)
- **Portra 400**, **Ektar 100**, **Vision3 5207 (Cinema)**, **Vision3 5219 (Night)**
- Fit data comes from a self-built calibration pipeline (color-chart captures → .cube → 12-sector
  hue joint/lab fitting) — not derived from third-party LUTs
- Each film carries its own look matrix, tone curves, post-curve 3x3 matrix and 12-sector hue
  matrices (hue_q10)

### 3. Local web build tool (original)
- `server.py + index.html`: pick films in the browser, build firmware in one click, download & flash
- XMP / .cube import → auto-fit into a new film → into firmware
- ΔE dashboard, film library management, official-firmware import guide, Mac/Windows launchers

## Usage

See `Mac使用说明.txt` (install Python → run the dependency installer → drop in the official
firmware → double-click the launcher). Requires your own Ricoh official firmware `fwdc239b.bin`
(2.10). This repository does not include or distribute any Ricoh firmware.

## Dependency: LLVM clang (required for firmware build)

Building firmware requires **clang (LLVM)** to assemble the ARM patches (grain engine, etc.).
The tool looks it up in this order: `CLANG` environment variable → `PATH` → common install
locations (e.g. `C:\Program Files\LLVM\bin\clang.exe` on Windows).

**Windows** (either one):

```bat
winget install LLVM.LLVM
```

or grab `clang+llvm-…-x86_64-pc-windows-msvc` from the
[LLVM Releases](https://github.com/llvm/llvm-project/releases) page and tick **"Add LLVM to
system PATH"** during setup. Reopen the terminal afterwards.

If clang is installed but not on PATH:

```bat
set CLANG=C:\Program Files\LLVM\bin\clang.exe
```

**macOS**: `xcode-select --install` (or `brew install llvm`). **Linux**: `sudo apt install clang`.

When clang is missing, the tool prints these install instructions instead of a cryptic error.

## License (by part)

- Engine code and notes: **GPL-2.0** (links [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool)
  (GPL-2.0) and Unicorn (GPLv2)). The upstream GR III research portions are © idontknownihil (MIT);
  the additions in this repository are © Duccio (Du Yuanjun).
- Duccio film fit data (`work/films_v16/fits/duccio/`, `work/duccio/` and related): © Duccio,
  **all rights reserved** (not licensed under the GPL; commercial use requires permission).
- `third_party/gr-custom-tool`: GPL-2.0 (vendored, kept under its own license).
- No Ricoh firmware, patched firmware images or photos are included.

## Disclaimer

Unofficial reverse-engineering research. Flashing modified firmware can permanently brick the
camera and voids warranty. Patches were verified only by offline emulation and on a single camera;
no guarantee they work or are safe on your device. Use entirely at your own risk. Not affiliated
with or endorsed by Ricoh Imaging.
