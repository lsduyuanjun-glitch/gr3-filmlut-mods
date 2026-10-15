# GR III fw 2.10 image-pipeline RE tools

**English** | [简体中文](README.zh-CN.md)

Custom film looks (Kodak Ektar 100, Gold 200, Portra 400, Fujifilm Pro 400H, Kodak Vision3 250D) and RAW-NR changes
for the Ricoh GR III firmware 2.10, built by patching the official update file offline. Research notes: `FINDINGS.md`.

## What it changes (films v10 / v11 builds)

| Image Control slot | Becomes | Film target (spektrafilm) |
| --- | --- | --- |
| Vivid | Ektar 100 | Kodak Ektar 100 on Portra Endura print |
| Retro | Gold 200 | Kodak Gold 200 on Portra Endura print |
| HDR Tone | Pro 400H | Fujifilm Pro 400H on Crystal Archive print |
| Cross Process | Portra 400 | Kodak Portra 400 on Portra Endura print |
| Bleach Bypass | Vision3 250D | Kodak Vision3 250D on Kodak 2383 print |

* Each film gets its own look matrix, its own R/G/B tone curves and a post-gamma 3x3 colour matrix (applied through the
  camera's RGB->YCbCr stage, so the Hue setting still works). Mode names and icons are replaced in all 21 UI languages.
* HDR Tone's local tone mapping and Retro's vignetting are switched off for these modes.
* RAW (Bayer) noise reduction is off up to ISO 8000 (stock behaviour above that). JPEG High-ISO NR is untouched.
* Standard, Monotone, Soft/Hard Monotone, Hi-Contrast B&W, Positive Film and Negative Film are byte-identical to stock.

## Current accuracy

Mean ΔE2000 (lower is better) between the camera's JPEG and the spektrafilm target, on a 252-patch hue chart shot on
the camera (ISO 200, Daylight WB). "Standard" = the unmodified Standard mode against the same target, for scale;
ΔE ≈ 1 is about a just-noticeable difference.

| Film | Standard vs target | v9 (camera) | v10 (camera) | v11 (predicted) |
| --- | --- | --- | --- | --- |
| Ektar 100 | 6.80 | 3.64 | 2.81 | 2.30 |
| Gold 200 | 6.05 | 3.20 | 2.22 | 1.87 |
| Pro 400H | 4.48 | 2.91 | 2.08 | 1.95 |
| Portra 400 | 6.36 | 3.14 | 2.28 | 1.98 |
| Vision3 250D | 6.59 | – | 2.49 | 2.42 |

The model predicts the camera to within ΔE 0.55-0.8, so the v11 numbers should hold, but v11 is not yet camera-tested.
Most of the remaining error is saturation; details in `FINDINGS.md` §22l-§22m.

**Not included:** any Ricoh firmware, patched images or photos. You need your own `fwdc239b.bin` (2.10).
The firmware container codec (`gr4_editor`) comes from [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool)
(GPL-2.0), included as a vendored copy in `third_party/gr-custom-tool` (kept under its own GPL-2.0 license, not
covered by this repo's license). Set `GR_CUSTOM_TOOL` to use another copy.

> [!WARNING]
> **Disclaimer — use entirely at your own risk.** This is unofficial reverse-engineering research. Flashing modified
> firmware is risky: it can permanently brick your camera, damage hardware, corrupt images or settings, and will
> almost certainly void your warranty and any manufacturer support. The patches were checked only by offline
> emulation and on a single camera; nothing guarantees they work or are safe on yours. The author accepts **no
> responsibility or liability** for any damage, data loss, bricked or broken devices, or any other consequence of
> using anything in this repository. If you are not prepared to lose the camera, do not flash it.
> Not affiliated with, endorsed by or supported by Ricoh Imaging; product names are trademarks of their owners.
> The software is provided "as is", without warranty of any kind (see `LICENSE`).

Film targets are rendered with [spektrafilm](https://github.com/andreavolpato/spektrafilm) LUTs, except Fujifilm
Classic Neg, which is fitted to the `classic neg_sRGB.cube` LUT of
[abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles). The fitted curves/matrices in
`work/**/fits` derive from these LUTs.

License (by part):
* Code and notes: **GPL-2.0** (`LICENSE`). Copyright (C) 2026 idontknownihil and Duccio (Du Yuanjun).
  This project builds on the GR III reverse-engineering work of idontknownihil and links against
  [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool) (GPL-2.0) and Unicorn (GPLv2), so the
  whole is distributed under GPL-2.0.
* Fit data derived from spektrafilm LUTs: everything in `work/**/fits/` except `classicneg_*`, plus `work/films/*.json`,
  `work/portra400/portra_fit.json` and `work/films_v8/cca1_mats.json`, `work/films_v9/cca1_mats.json`. Derived from
  [spektrafilm](https://github.com/andreavolpato/spektrafilm) by Andrea Volpato, licensed CC BY-SA 4.0 (spektrafilm
  license with the full CC BY-SA 4.0 text: `LICENSES/SPEKTRAFILM_LICENSE.txt`). Modified by idontknownihil: the LUTs
  were fitted to GR III camera parameters (see `LICENSES/CHANGELOG.txt`); the LUTs themselves are not included.
  Adaptations must stay CC BY-SA 4.0 and keep this credit.
* Fit data derived from FujifilmCameraProfiles LUTs (`work/**/fits/classicneg_*`, i.e. every fit whose `spec` points to
  that repo): [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) (text in
  `LICENSES/CC-BY-NC-SA-4.0.txt`). Attribution: adapted from `classic neg_sRGB.cube` by abpy,
  [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles), CC BY-NC-SA 4.0. Changes: the LUT was
  fitted to the GR III look matrix, tone curves and post-curve matrix; the LUT itself is not included. Provided as is,
  without warranties (license section 5). Non-commercial use only, and adaptations must be shared under the same
  license. This also applies to any firmware image built with these fits: don't sell it or distribute it commercially.
* `third_party/gr-custom-tool`: GPL-2.0 (its own `LICENSE`).

Offline only. Input: `../fwdc239b.bin` (SHA-256 `d6a3c9c2…54bfd4`). Addresses are valid for this file only.

Setup (Python 3.12):

```sh
python3 -m venv .venv && .venv/bin/pip install capstone numpy unicorn==2.1.4
mkdir -p work/fw
.venv/bin/python -I -c "
import sys; sys.path.insert(0,'.'); import codec_path
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload
d=open('../fwdc239b.bin','rb').read(); i=inspect_container(d)
dec,_=decode_payload(d[128:i['payload_end']], i['decoded_size'])
open('work/fw/rtos.bin','wb').write(dec[0x10870:0x10c5e30])"
```

| File | Purpose |
| --- | --- |
| `codec_path.py` | Puts the gr-custom-tool submodule (or `$GR_CUSTOM_TOOL`) on `sys.path` for `gr4_editor` |
| `fw.py` | RTOS address helpers, xrefs (MOVW/MOVT, BL, literal), disassembly |
| `emu.py` | Unicorn harness (allocator/assert/log/SVC stubs) |
| `run_tuning.py` | Runs `ImageTuningStill::Make` for a given internal tone slot and returns the R2Y parameter block |
| `diffmodes.py`, `sens.py` | Diff R2Y output across modes / per image parameter |
| `cube_fit.py` | Fits .cube LUT(s) to look matrix + Cross Process curves (run in a venv with colour-science/scipy, e.g. spektrafilm's) |
| `make_film.py` | Writes a cube_fit result into Cross Process (own record + matrix + 9 curves) |
| `verify_film.py` | Offline checks + emulated R2Y diff of a make_film output vs stock |
| `make_films.py` | Four film modes over Cross Process / Vivid / Retro / HDR Tone (records, curves, selector code patch) + icons + names (FINDINGS §14) |
| `make_icons.py`, `make_names.py` | Redraw the mode icons in ICONBIN / rename the modes in all 21 UI languages (used by make_films) |
| `verify_films.py` | Offline checks of a make_films output (emulated still + LV, names, icons) |
| `make_ma_probe.py`, `make_ma_probe2.py`, `verify_ma_probe*.py`, `make_hue_chart.py` | MultiAxial probe firmwares (FINDINGS §15, §16) and their chart |
| `raw_nr.py` | RAW (PPU Bayer) noise reduction patches: off (`make_films.py --raw-nr-off`, §21) or only at ISO ≥ 6400 (`--raw-nr-from-6400`, §21b) / above a given ISO (`--raw-nr-above 8000`, §21c) |
| `raw_noise.py` | Measures noise correlation in DNGs to detect raw NR (FINDINGS §21) |
| `cca1.py`, `cca1_fit.py`, `verify_cca1.py` | Per-film post-gamma 3x3 (CCA1) warm-colour fix: fit, patch (`make_films.py --cca1`), emulated check (FINDINGS §22g) |
| `joint_fit.py` | Joint refit of look matrix + film curves + CCA1 for a film fit (films v9, FINDINGS §22i) |
| `make_films10.py`, `film_cave.py`, `armasm.py`, `verify_films10.py` | Films v10: five films (Bleach Bypass -> Vision3 250D, knot-stored curves), post-gamma 3x3 via the RGB->YCbCr matrix, emulated check (FINDINGS §22l; needs Homebrew llvm for llvm-mc) |
| `lab_fit.py` | Perceptual (dE2000) refit of a joint fit: look matrix + post matrix + curve corrections (films v11, FINDINGS §22m) |
| `make_cca1_probe.py` | Temporary v7 + red/blue swap in CCA1 (proved CCA1 is live) |
| `eval_warm.py` | Warm-hue (yellow/orange) vs overall error of film fits (films v3, FINDINGS §19) |
| `gr3patch.py` | Proof-of-concept builder: patches a look matrix and repacks a container (reuses stock frames) |

Camera-tested on one GR III (fw 2.10): films v2-v10 and the RAW-NR builds (FINDINGS §14-§22m). Films v11 is untested.
