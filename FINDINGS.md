# Ricoh GR III fw 2.10 — image pipeline & film-filter findings

Investigated 2026-10-07. Static analysis + Unicorn emulation of the RTOS; **nothing has been flashed or tested on a camera.**

## 1. Input and tooling

- Firmware: `~/dev/gr3-firmware/fwdc239b.bin`, GR III, version 2.10.21.27, SHA-256 `d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4`. All addresses below apply to this file only.
- Container format = same family as GR IV; `gr-custom-tool/gr4_editor/codec` decodes it (2430 frames, decoded 0x38F3AF4 bytes).
  - Project id 0x24C (GR IV is 0x27C), 14 sections incl. extra `FDRVPARA`, no metadata records → the GR IV editor refuses it (hard-coded to GR IV 1.11.10.7 SHA). Its public release also deliberately excludes the filter feature.
- Decoded sections: BOOTPARA, DRAMPARA, PARTPARA, M0, BOOT, RTOS @0x10860 (payload +16), LINUX, INITFS, SRIC, CPU, SHELLCMD, ICONBIN, FDRVPARA, RES (DF_EX.bin / DF_IP.bin / DF_ID_S.bin = DSP code for digital filters, not tables).
- RTOS: ARM mode, base 0x53000000. Initialized data copied at boot from ROM 0x5407B540 → RAM 0x55000000 (len 0x3A080). Patch RAM-addressed data at `file = addr - 0x55000000 + 0x5407B540`.
- Functions start with `mov ip, sp`; call there (not at the `push`) when emulating.
- Tools in this folder: `fw.py` (xrefs/disasm), `emu.py` (Unicorn harness), `run_tuning.py` (runs ImageTuningStill::Make), `diffmodes.py`, `sens.py`, `gr3patch.py` (PoC patch builder). See README.md.

## 2. Still pipeline (BE still recipe steps)

`PRO_SRO → B2B → B2B_B2R_R2Y → CNR → DIGITAL_FILTER → RESIZE(IIP) → JPEG_ENC`

- R2Y core blocks (from register-dump strings): CNTL, OFG (WB gain/offset), CCA0 (3×3 matrix CC0K + Y-dependent CC0YB*), BTC/TC (tone control), GAM (gamma), CCA1, YNR, edge enhancement, YBCRV, CLPF, CSP (RGB→YCbCr).
- IIP engine (DIGITAL_FILTER / resize): 1D loader, Affine, FreeRect, Blend, CSC, GPC, LUT units A–F (1D, with pre-calc), MinMax, Monitor, SPF, Store. **No 3D LUT hardware anywhere.**
- DIGITAL_FILTER dispatcher 0x535032B8: 6 ops (Effect 0x53680DBC fed by 0x5350304C, 0x536793C0, Demoire 0x53685D24, 0x53682A58, 0x5368AA9C, 0x53682004). Effect op reads only SI+0x793..0x796 (shading/clarity/grain-type params); no mode-dependent branch.

## 3. ImageTuning (R2Y parameter generation)

- `ImageDevelopmentPipeService::MakeImageTuningParameter` 0x5365C144 → virtual Make (vtable+0x1C).
- Vtables: ImageTuning base 0x53DBD240; Still 0x53DBD8A0 (Make 0x536DD8F0); LiveView 0x53DBD938 (Make 0x536DDECC); init methods 0x536DA1FC (creates sub-tunings) and 0x536DA62C (buffers/defaults).
- Sub-tuning objects (ImageTuning+off, Make fn): +0x154 Interpolation 0x536DECB4, +0x158 ColorMatrix 0x536DF3D4 (calc 0x536DEECC), +0x15C MultiAxial 0x536E4470 (calc 0x536DF484, write 0x536DF55C), +0x160 LumaNr, +0x164 YCbCrMatrix 0x536E4760, +0x168 ColorReference 0x536E4C1C, +0x16C CoordinateScale, +0x170 ColorLpf, +0x174 EdgeEnhancement, +0x178 YCbCrOperation 0x536E77DC (calc 0x536E73D0), +0x17C Gamma 0x536E9000 (calc 0x536E8FBC, write 0x536E7A24), +0x180 ToneControl 0x536E9D1C (calc 0x536E9BD8, write 0x536E91A8), +0x184 ResizeEdge, +0x188 Suppre, +0x18C Reduce.
- Context fill: 0x536DD270, 0x536DB130, 0x536DC0F4 (+ 0x536DB7D8 param pass-through). Input `info`: +0x82AC stage (0 LV, 1/2 still), +0x82D0 ShootingInfo ptr (still uses SI+0x71248). R2Y output block = info+0x120.
- LiveView Make calls the same sub-tunings (gated by dirty flags obj+4..+0x12) → **changes show in live view** (confirmed by emulation).

## 4. Mode identification (confirmed)

- Internal tone = ShootingInfo+0x77C. EXIF Pentax ImageTone 256+n → 11+n (table 0x53D2D920). UI code (e.g. GetDefaultValueSaturation 0x532C34EC) switches on tone-11.

| Tone | Mode | Record slot |
|---|---|---|
| 11 | Standard | 11 |
| 12 | Vivid | 12 |
| 13 | Monotone | 13 |
| 14 | Soft Monotone | 14 |
| 15 | Hard Monotone | 15 |
| 16 | Hi-Contrast B&W | 16 |
| 17 | Positive Film | 17 |
| 18 | Bleach Bypass | 18; SI+0x786=2 → 22, =3 → 23 |
| 19 | Retro | 19 |
| 20 | HDR Tone | 20; SI+0x788=1/2 → 24 (mono) |
| 21 | Cross Process | 21 (SI+0x797 = preset 0/1/2) |
| 22 | Negative Film | 25 |

- Slots 0–10 are unreachable legacy looks with full data (likely Pentax custom images; by saturation: 0 identity, 1 = Vivid matrix, 3 ~1.3× "landscape", 4 green-boost "vibrant", 5 ~2× "radiant", 6 ~0.75× "muted", 7 ~0.95, 8 ~0.55 hue-shifted, 10 mono). Names unconfirmed.

## 5. Per-mode look record (confirmed)

- Pointer table RAM **0x55018D94**[slot] → 0x54-byte record of 17 pointers.
- Other per-tone tables in ctx fill: 0x55018CF0 (all same), 0x55018E4C (mono/variant flag-ish), ColorRef uses 0x53DC5750 when tone==9.
- Record fields:
  - f0: camera base matrix (s16)
  - **f1: look matrix, 9 × s16 Q13 (0x2000 = 1.0), row-major, rows = out R,G,B, rows sum to 1.0**
  - f2: array of matrices indexed by saturation step (mono records: mono conversion)
  - f3, f4: extra (f4 → luma coeffs 77/150/29)
  - f7, f11–f14: YCbCrOperation — **toning** (Cb/Cr offset tables indexed by toning param ctx+0x60)
  - f15/f16: ToneControl 4 offsets (only Retro nonzero: (-32,0,120,0)/(-16,0,60,0))
- Final CCA0 = A(saturation) · Look · CameraMatrix, then global saturation scale, clamped 12-bit signed, Q8 (row sum 256). Example Standard `[436,-184,4,-48,400,-96,1,-104,359]`.
- Look matrix addresses (single-referenced unless noted): Std/HDR/Cross share 0x53DC2754; Vivid 0x53DC26DC; Positive 0x53DC272C; Bleach 0x53DC2474 (var 0x53DC26F0, 0x53DC24C4); Retro 0x53DC2818; Negative 0x53DC2AD0; Mono+slot24 share 0x53DC2A94.

## 6. What actually differs between modes (emulated, neutral params = 4)

- Standard vs Vivid/Positive/Negative/Retro/Bleach: **only the color matrix** (+toning tables, Retro offsets). Gamma/tone curves identical. Mono modes: matrix with identical rows + YCbCr chroma.
- Per-mode tone curves exist only for:
  - **Cross Process**: per-channel R/G/B curves composited into gamma (0x536E87A8, gated by ctx+0x9B = SI+0x38A98≠0). Curve library RAM **0x55037604** = 12 × 256-entry u16 (14-bit) curves at ROM 0x53EFB0E4… (0x200 each). Presets: sub0 = R3,G4,B5; sub1 = R6,G7,B8; sub2 = R9,G10,B11. Curves 0–2 unused. Selector object 0x5536DAB8 (+0xE/+0xF/+0x10 = R/G/B index); getter 0x536EEDF0.
  - **Hi-Contrast B&W**: DigitalFilterGammaCoordinator (singleton 0x5536DBFC, RTone/GTone/BTone 256-entry) via 0x536F0290 when tone==16.
- Param mapping (SI offsets): 0x77D saturation → matrix; 0x77E hue → YCbCr matrix; 0x780 contrast, 0x781 highlight contrast, 0x782 shadow contrast → gamma; 0x784.. sharpness etc.; 0x793–0x796 → DIGITAL_FILTER effect.
- Gamma write: 4 tables × 0x800 bytes at out+0x2568/0x2D68/0x3568/0x3D68 (R,G,B,Y — packed register format) + 4 × 0x200 at +0x4768…; patching curve 3 changes table 0 (R) and table 3 (Y) only.
- Other gamma data: DR/brightness-blend curves table RAM 0x550204E0 (31 curves, 7 levels); "BasicGammaTableNatural/Reversal" are copied into ShootingInfo for metadata, not imaging. ToneControl is scene-adaptive (histogram-based).

## 7. MultiAxial (hue-area color correction) — partially confirmed

- Calc 0x536DF484, write 0x536DF55C → output info+0x120+0x100…0x6FF.
- Source set struct ROM 0x53DC2BA0: [0] 16 × u16 boundaries (0x53DC3198), [1] 20 × 4-bit area selectors (0x53DC2BB8), [2] RAM 0x55019828 → table 0x53DC31D0 = **540 int32 = 60 × 3×3 matrices (Q10)**, [3]→ 10-bit table, [4] 12-bit thresholds, [5] RGB→YCbCr coeffs (77,150,29,-43,-85,128,128,-107,-21…).
- Table entry i maps linearly to 12-bit register fields (6 blocks × 90 entries, 0x100 bytes per block).
- **GR III ships boundaries and selectors all zero → inactive.** Only block 0 matrix 0 non-identity.
- Geometry (how boundaries/selectors partition Cb/Cr hue) is **unconfirmed**; no public docs (Socionext M10V/SC2000 register manual is NDA). Closest public description: axis-based hue/saturation remapping patents (US7907148, US7903178), not confirmed as Fujitsu/Ricoh. Needs camera test with marker values.

## 8. Firmware update acceptance (static)

- FwDecoder (0x5362BD44 header, 0x5362BEA8 decoded sum, 0x5362BF4C decode): checks header project (0x30), [0x78]==proj|proj<<16, [0x7C]==0xA55A5AA5, footer project/marker/fw type, container additive sum32==0, decoded size, **decoded sum32==0** (last decoded word is the fixer).
- Version check 0x536284E4: (major<<16|minor) of file **≥** current → same 2.10 accepted.
- No signature/RSA found in RTOS updater; BOOT loader strings only report load errors.
- Special SD files: C:\FWBYPASS, C:\FWDEL.BIN, C:\NOWAIT, C:\NOOFF.BIN, C:\KBCHG.BIN.

## 9. Proof of concept (offline)

- `gr3patch.py` patches Retro's look matrix (0x53DC2818) with a warm matrix, repacks with `_repack_frames` (2428/2430 stock frames reused, 30,415,816 bytes).
- Verified: all updater checks pass; re-decode differs only in the 18 matrix bytes + checksum word; emulated Retro CCA0 changes `[261,-24,19,…]` → `[492,-266,30,…]` (still & live view), Standard unchanged.
- Test file was written to the session scratchpad (`out/fwdc239b_retro_test.bin`); regenerate with `gr3patch.py` if needed.

## 10. Other useful facts

- SHELLCMD section: ~585 engineering commands incl. CAP_REG_B2Y, CAP_REG_IIP, CAP_DumpImageMap, CAP_Lut, SYS_md/SYS_mm, SYS_script, lcmd (Linux shell bridge). Access path on GR III unverified.
- C:\SYSPARAM.TXT (DebugInfoOfferer 0x536555E0) = sensor/engineering debug flags only (DUMP_STILL_REGISTER, DUMP_B2B_REGISTER…), nothing color.
- Engineering/TTL interfaces documented for GR IV in `~/dev/ricoh-gr4-firmware-analysis-and-feature-expansion`.

## 11. How to build a LUT-style film filter

No 3D LUT → decompose a target LUT into:
1. **Look matrix** (record f1) — data patch, confirmed.
2. **Per-channel 1D curves** — replace a Cross Process preset's 3 curves in the 12-curve library (data patch, confirmed); or small code patch to enable the RGB-curve path for another mode.
3. **Toning tables** (f11–f14) for split-tone highlights/shadows.
4. **MultiAxial** hue-area matrices for selective color — after its geometry is learned on camera.

## 12. Open items / next steps

1. Flash test: does the camera accept/boot a patched file? (Keep stock fwdc239b.bin to reflash.)
2. MultiAxial geometry: flash a variant with marker boundaries/matrices, shoot a color chart.
3. RAW+JPG validation: same scene per mode (tripod, M mode, Daylight WB, ISO 200, all params 0, DR/Clarity/Shading off; plus Standard Contrast+2 and Saturation+2). Develop DNG through the extracted model and compare to camera JPG.
4. ~~Tool: `.cube` → matrix + curves fitter~~ done, see §13.
5. Confirm the gamma-index exposure assumption (§13) with a RAW+JPG pair; refit if mid gray isn't at index ~7.8.
6. Yellow→orange hue shift of Portra needs MultiAxial (after its geometry is known).

## 13. Portra 400 via spektrafilm (built offline, 2026-10-07)

Source: `~/dev/spektrafilm` (v0.3.4). `spektrafilm-lut build --film kodak_portra_400 --print kodak_portra_endura --input vlog --output srgb --resolution 33` (+ a `fujifilm_crystal_archive_typeii` print variant). LUTs are CC BY-SA 4.0 + spektrafilm LUT license → credit spektrafilm, share alike, no resale.

**Cross Process composite (0x536E8668, confirmed):** when ctx+0x9B≠0 each channel's 256-entry gamma becomes `out_c[i] = Curve_c(Base[i])` (index Base>>6, 6-bit lerp, entries ≥255 use the last value); Y table = (77R+150G+29B)>>8 of the composites. Base = Standard 256-entry 14-bit gamma (dumped: `work/base_gamma_std.npy`, identical for Std/Cross at neutral params).

**Model used by `cube_fit.py`:** `code_c = Curve_c(Base(K·(M·L)_c))/16384`, L = linear sRGB after camera matrix. **Assumption:** Base index domain is linear and 18% gray lands at index ≈7.8 (Standard → sRGB ≈0.46), K = 7.8/0.18. Needs RAW+JPG confirmation.

**Fit (shared M, 3 presets, gray weighted as near-hard constraint, skin 3×):**
| Cross preset (SI+0x797) | Target | Chart ΔE2000 mean / max | Standard vs target |
|---|---|---|---|
| 0 | Portra 400 → Portra Endura | 3.0 / 11.5 | 5.7 |
| 1 | same, +1 EV (overexposed Portra) | 3.3 / 10.2 | 12.2 |
| 2 | Portra 400 → Fuji Crystal Archive | 2.3 / 7.3 | 5.3 |
Grays within ~1/255. Residual errors are yellows/oranges (Portra rotates yellow toward orange) — not expressible with matrix+per-channel curves; MultiAxial territory.
M = [[0.786,0.246,-0.032],[-0.014,0.862,0.152],[-0.007,0.039,0.968]].

**Patch (`make_film.py`, data only):** Std/HDR/Cross share record 0x5501900C and matrix 0x53DC2754, so: copy that record over unreachable legacy record of slot 2 (0x5501939C), keep its f1 → 0x53DC2A54 (single-ref), write M there (Q13), set RECORDS[21] = 0x5501939C; overwrite curves 3–11 (each ROM curve pointer single-referenced from the library table). Note: a second record table at RAM 0x55037634 (used by 0x536EFAA8, caller unknown) also lists slot-2's record at its index 2; Cross/HDR aren't in that table.

**Verified offline (`verify_film.py`):** container & decoded sum32 = 0, only RTOS bytes changed, Standard and HDR R2Y output byte-identical to stock, Cross presets 0–2 composite curves = fitted curves (±1/16384), CCA0 `[436,-184,4,-48,400,-96,1,-104,359]` → `[338,-85,3,-43,305,-6,12,-120,364]`.

Output: `work/portra400/fwdc239b_portra400.bin` (SHA-256 95dc0989…1d79d3), fit `portra_fit.json`, preview `portra_preview_small.jpg` (columns: Standard model | camera-achievable fit | spektrafilm target; rows = presets 0/1/2). Menu still says "Cross Process" (UI strings not patched). **Not flashed.**

The Portra build in §13 was flashed and works on the camera (2026-10-07).

## 14. Four film modes replacing Cross Process / Vivid / Retro / HDR Tone (built offline, 2026-10-08)

`make_films.py` (+ `make_icons.py`, `make_names.py`), check with `verify_films.py`. Output `work/films/fwdc239b_films.bin` (SHA-256 25ca2899…97b3ea), previews `charts.png` (Standard | fit | target), `icons.png`.

| Menu slot (tone) | Film (spektrafilm v0.3.4, print) | Curve set (selector) | Record | Chart ΔE2000 fit / Standard |
|---|---|---|---|---|
| Cross Process (21) | Portra 400, Portra Endura | 2: R3,G4,B5 | legacy slot 2 0x5501939C | 2.9 / 5.7 |
| Vivid (12) | Ektar 100, Portra Endura | 4: R9,G10,B11 | own 0x550196D8 | 3.4 / 6.2 |
| Retro (19) | Gold 200, Portra Endura | 3: R6,G7,B8 | own 0x55019108 | 2.7 / 5.2 |
| HDR Tone (20, also slot 24) | Pro 400H, Crystal Archive | 3 (shared with Retro, matrix-only fit) | legacy slot 1 0x55019060 | 3.3 / 4.3 |

**Curve-set selector.** SI+0x38A98 (→ ctx+0x9B) maps via table 0x53DBD19C (`[8,0,1,2,3,…]`) to a Cross mode for 0x536EF140: value 2/3/4 = Cross preset 0/1/2 with fixed curve indices; value 1 = Cross "random" (0x536EF618, rand()%6 / %9 → not deterministic, still and LV differ); 5..8 copy a saved set from SI+0x38A9A via 0x536EEE30. So only three independent curve sets exist; the composite works for any tone once the selector is non-zero.

**Code patches (equal size):** 0x536DD450 `ldrne`→`ldr`, 0x536DD454 `beq`→`b` into 0x536DD4B8, where the old Cross-preset chain is replaced by `mov r2,#0; cmp r1,#tone; moveq r2,#sel …; strb r2,[r3,#0xa98]` for tones 12/19/20/21. 0x536DBEB4 `ldrb sb,[r3,#0x788]` → `mov sb,#0` (HDR Tone passes HDR intensity 0 at ctx+0x1F0, as Standard does). 0x536DC27C `beq` → `nop` (HDR always record slot 20; the SI+0x788=1/2 branch chose mono slot 24). ImageTuningStill::Make output for HDR vs Standard differed **only** in ctx+0x1F0, i.e. the HDR effect runs in another stage that I have not located; whether intensity 0 switches it off is unconfirmed until tested on camera.

**Icons:** tone→icon 0x532935DC: Vivid 0x224, Retro 0x164, HDR 0x15F, Cross 0x32 (each 40×40, single descriptor, unique pixels). Redrawn on the Positive Film film-strip frame (0xE8) with labels P400 / E100 / G200 / 400H.

**Names:** string table 0x55002BAC[21 langs][0x311]; entry = {u8 chars incl. NUL, u8 1, u16 0, u32 → UTF-16LE}. Tone→string id 0x532922B4: Vivid 0x10C, Retro 0x114, HDR 0x115, Cross 0x116. New name written over the longest translation of the id; all 21 language entries repointed (Portra 400 / Ektar 100 / Gold 200 / Pro 400H).

**Verified offline:** sums 0, only RTOS+ICONBIN changed, Standard/Monotone/Positive/Bleach/Negative R2Y byte-identical to stock (still and LV), each film mode's composite = fitted curves (±1/16384) in still and LV, names/icons read back. Cross presets 0–2 now all give Portra 400. Not flashed.

### 14a. Camera test 1 (`../photo-test1`, 2026-10-08) and v2

Same scene, ISO 200, Daylight WB, 1/2000 f/3.2, all sub-settings 0; R0011725 Standard, 21 Cross→Portra, 24 Vivid→Ektar, 23 Retro→Gold, 22 HDR→400H. DNG developed linear (rawpy, camera WB, sRGB primaries), JPG aligned by ECC, 375×250 px. Standard fitted as JPG = BaseGamma(A·lin) (dE 3.4 mean; residual = in-camera lens shading + shadow lift). Then each film JPG vs my model with the same A:

| Shot | camera vs model ΔE | camera vs film target ΔE | luma residual corners / highlights |
|---|---|---|---|
| Standard | 3.4 | — | +15 / −6 (shading corr., baseline) |
| Portra (Cross) | 3.2 | 4.0 | same as Standard |
| Ektar (Vivid) | 3.1 | 4.0 | same as Standard |
| Gold (Retro) | 8.1 | 8.7 | −50 / −37: **vignette + flattened highlights** |
| 400H (HDR) | 5.5 | 6.0 | shadows +15, highlights −17: **HDR local tone mapping still on** |

Portra/Ektar behave exactly as modelled (residual identical to Standard's) → curve composite, matrices and the exposure assumption (scene median at base-gamma index 8.2 under AE, assumed mid gray 7.8) hold; no refit needed. Retro and HDR have effects outside ImageTuningStill::Make (emulated Make output differs from Standard only in matrix/curves plus Retro's ctx+0x1F0 toning=4 and ctx+0x1FC=4).
v2 (`work/films_v2/fwdc239b.bin`, SHA-256 7528690b…edbeb699) adds: HDR SI+0x796/ctx+0x1FA forced 0; 0x535131C0 local-process gate for HDR = Standard's (was SI+0x796≠0); Retro ctx+0x1FC 4→0. Both are best guesses — needs camera test 2. Fallback if they don't work: put Gold 200 / Pro 400H on Positive Film (17) / Bleach Bypass (18), which Make treats like Standard.

### 14b. Camera test 2 (`../photo-test2`, v2 firmware) — Retro/HDR fixed

Indoor scene, ISO 200, Daylight WB. Standard R0011736 (1/200 f/2.8, **DR expansion Off**, BaselineExposure −0.51); films 1/20–1/15 f/8 with DR expansion On (BaselineExposure +0.49, i.e. raw 1 EV under + digital gain) — corrected by ×2^1.0 on the linear data. A monitor showing video is in frame.

| Shot | camera vs model ΔE | camera vs film target ΔE | luma residual corners |
|---|---|---|---|
| Standard (fit) | 2.5 | — | +13 (lens shading corr.) |
| Portra (Cross) R0011740 | 3.3 | 3.8 | +5 |
| Ektar (Vivid) R0011737 | 2.4 | 3.3 | +7 |
| Gold (Retro) R0011738 | 2.6 | 3.1 | +7 (was −50 in test 1) |
| 400H (HDR) R0011739 | 2.6 | 3.7 | +8 (no local tone mapping) |

Retro's vignette/highlight flattening and HDR's local tone mapping are gone; all four slots now match the model like Standard does. So ctx+0x1FC=4 drove Retro's effect, and SI+0x796 / the 0x535131C0 gate drove HDR's. v2 is the build to use.

## 15. MultiAxial probe, round 1 (built 2026-10-08, not yet shot)

Register mapping (emulated, halfword index in info): YCbCr coeffs 208–216; 16 boundaries 224–239 (12-bit); 20 selector **bytes** (4 bits used) → 240–247 packed 5 per 2 halfwords; matrices 272.. (12-bit signed Q10, ±2.0, value 4096 wraps); control block (set[4] = selector block + 0x14): [0] 6-bit field at byte 0xA00 (hw 1424), [1..8] 12-bit thresholds 1428–1435 (stock 4095), [9..20] 1436–1450 (32, 0,0,21,62,0,1,2,7,0,640,1280); set[3] object → +0x10 → **360** × 10-bit table (stock all 0) → hw 1040…; per-tone set table 0x55018CF0 (Negative = slot 25). Calc copies from ctx instead when ctx+0x94≠0 (not seen in emulation).
Stock matrix 0 = (420,76,16 / 38,458,16 / 38,76,398) = 0.5·(0.75·I + 0.25·luma) in Q10 — would halve brightness if used, so the stock config either bypasses the block or never selects matrix 0.

Probe `make_ma_probe.py` → `work/ma_probe1/fwdc239b.bin` (SHA-256 53af0563…a35b41), checked by `verify_ma_probe.py`. All 60 matrices = gain·I with gain LEVELS[m % 8] = 0.85…0.18 (bypass = 1.0); data in the Cross curve ROM area (Cross curves disabled). Probe modes all use the Standard look record (+ HDR/Retro extras off), so vs. a Standard shot the only change is MultiAxial:

| Mode | boundaries | selectors | control[0] | thresholds |
|---|---|---|---|---|
| Vivid | i·256 | i (0..15), 0×4 | 0 (stock) | stock |
| Positive | i·256 | i | 1 | stock |
| Negative | i·256 | i | 0x3F | stock |
| Retro | i·256 | all 5 | 0 | stock |
| HDR Tone | i·256+128 | i | 0 | stock |
| Cross | i·256 | i | 0 | 511,1023…4095 |

Chart: `make_hue_chart.py` (36 hues × 6 sat/brightness rows + gray row, corner markers).

### 15a. Probe round 1 result (photo-ma1, R0011749-54, 2026-10-08)
Shot: Standard, Vivid, Negative, Positive, Retro, HDR (no Cross, no closing Standard). Every probe
mode came out identical to Standard: per-patch (36x7) differences <= 3.6/255 in every channel,
mean brightness ratio 1.000-1.008, versus the designed 0.85..0.18 gains. All modes showing the
Standard look confirms the probe firmware was running (stock Negative/Positive/Retro look different).
=> MultiAxial is bypassed for stills regardless of boundaries/selectors/control[0] (0, 1, 0x3F)/
matrices, even though the emulated register image matches the design. The enable must be elsewhere
(a module enable/bypass bit in another register block, or the info+0x120 image is not the one the
still path loads). Next: find who reads info+0x120 MultiAxial registers / the module enable mask.

## 16. MultiAxial probe, round 2 (built 2026-10-08, not yet shot)

Why round 1 did nothing (emulated write trace of the info block, `re/regmap.py` in the session scratchpad):
MultiAxial is part of the **CCA0 register group** at info+0x120, not a separate block.
- byte +0x00 bits 0-1 = **CC0CTL** (2-bit), written by the ColorMatrix writer 0x536DF13C from calc out[0],
  which the calc **hard-codes to 1** (0x536DEF10 `mov r3,#1`) for every mode, still and LV.
- +0x20..0x30 CC0K matrix, +0x40..0x56 Y-dependent blend (CC0YB*), +0x80.. MultiAxial (writer 0x536DF55C).
- The matrix registers are 5 per 0x80 bytes, stride 10 halfwords: matrix m at hw 272 + 64·(m//5) + 10·(m%5).
- info+0x1220 = a second group (CCA1-like, 2-bit ctl at +0x1220 from ColorMatrix out+0x30, stock 0).
Hypothesis: CC0CTL 1 = linear matrix only; 2/3 switch MultiAxial in (instead of / in addition to CC0K).

`make_ma_probe2.py` → `work/ma_probe2/fwdc239b.bin` (SHA-256 99c916af…a01200), checked by `verify_ma_probe2.py` (ALL OK).
- Per-mode CC0CTL via a tag in the probe sets' YCbCr array halfword 9 (stock padding 0) = 0xA500|ctl; MultiAxial Make's
  tail call 0x536E4498 → stub at 0x536DD4B8 (dead Cross-preset code, round-1 patches kept) that rewrites CC0CTL bits 0-1.
- Matrices: m = diag(R,G,B), G = 256·LEVELS[m%10] (1.0 … 0.21), R/G,B/G = TINTS[m//10]; peak 256 ≤ 1.0 in Q8/Q9/Q10.
- Boundaries i·256, selectors i (Cross: all 0).

| Mode | CC0CTL | selectors | control[0] |
|---|---|---|---|
| Vivid | 2 | i | 0 |
| Positive | 3 | i | 0 |
| Negative | 2 | i | 0x3F |
| Retro | 3 | i | 0x3F |
| HDR Tone | 0 | i | 0 |
| Cross | 2 | all 0 | 0 |

### 16a. Probe round 2 result (photo-ma2, R0011755-63, 2026-10-08)
Patch analysis (`ma2/*.py` in the session scratchpad): JPG → base-gamma index, fitted 3×3 vs Standard. RAW patches equal
across shots (<1 %), Standard vs closing Standard identical (index rms 0.05).
- **CC0CTL is a gain on the CC0K output, not a MultiAxial enable**: 0 → ×0.50, 1 → ×1 (stock), 2 → ×2.0, 3 → ×3.9 (clipped).
  Fitted G ≈ diag gain with small off-diagonals; Neg (ctl0 0x3F) = Vivid, Retro (0x3F) = Positive → control[0] no visible effect.
- MultiAxial **is running at stock CC0CTL**, but weakly: zones with selectors = i vs. all-equal selectors give a hue-local
  change (yellow-green..green −2 codes at ×1, −8 at ×2; cyan..magenta +1), the same pattern in round 1 (Vivid/Neg/Pos/HDR vs
  Standard; Retro with all selectors 5 ≈ Standard). The coded matrices (gains 0.2–1.0) do **not** show → they are gated.
  Candidates: the 360-entry per-degree table (stock 0) and/or the thresholds (stock 4095).

## 17. MultiAxial probe, round 3 (built 2026-10-08, not yet shot)
`make_ma_probe3.py` → `work/ma_probe3/fwdc239b.bin` (SHA-256 952bc302…3db7b2b), `verify_ma_probe3.py` ALL OK. Stock CC0CTL,
round-2 matrices, bounds i·256. Hue table = 360 × 384 (int32 source, written as 10-bit) at 0x53EFC198, own object.

| Mode | thresholds | hue table | selectors |
|---|---|---|---|
| Vivid | 0×8 | stock 0 | i |
| Positive | 511…4095 ramp | stock 0 | i |
| Negative | stock 4095 | 384 | i |
| Retro | 0×8 | 384 | i |
| HDR Tone | ramp | 384 | i |
| Cross | 0×8 | 384 | all 0 |

### 17a. First round-3 shoot (photo-ma3, R0011764-72) was taken on round-2 firmware
Per-mode gains reproduce round 2 exactly (Vivid/Neg/Cross ×2.0, Pos/Retro ×3.9, HDR ×0.51; Vivid≈Neg, Pos≈Retro, Vivid vs
Cross green difference ≤8 codes), which the round-3 build cannot produce (CC0CTL 1 in every mode). The SD card held the
round-3 file (SHA 952bc302…, copied 19:13) but the update was evidently not applied. Reshoot needed after flashing.
Quick check after flashing round 3: Vivid must NOT be ~1 stop brighter than Standard.

### 17b. Probe round 3 result (photo-ma3, R0011773-81, 2026-10-08)
Round-3 firmware confirmed running (no gain changes). Every probe mode is within dE2000 0.9 of Standard (Std vs Std2 0.5):
thresholds 0 / ramp / stock × hue table 0 / 384 do **not** let the coded matrices act. All probe modes, Cross with
selectors 0 included, show the same ≤3-code (≤6 for Cross) dip in yellow-green..green → that small effect is probably
not MultiAxial at all (some other non-Standard-mode difference), so §16a's "MA runs weakly" is withdrawn.
=> No field of the MultiAxial set (bounds, selectors, control[0], thresholds, hue table, matrices) and no CC0CTL value
makes MultiAxial act on stills.

## 18. MultiAxial probe, round 4 (built 2026-10-08, not yet shot) — last planned
`make_ma_probe4.py` → `work/ma_probe4/fwdc239b.bin` (SHA-256 feec3736…de33416), `verify_ma_probe4.py`.
Tests an enable bit elsewhere in the CCA0 header (info+0x120..0x13F; only CC0CTL bits 0-1 are ever written): per mode a
32-bit OR mask via the round-2-style stub (tag 0xA500|offset, mask in YCbCr array hw 10-11). MA config: bounds i·256,
selectors i, stock thresholds, hue table 384, coded matrices.

| Mode | header word | OR mask |
|---|---|---|
| Vivid | +0x00 | 0x000000FC |
| Positive | +0x00 | 0x0000FF00 |
| Negative | +0x00 | 0xFFFF0000 |
| Retro | +0x04 | 0xFFFFFFFF |
| HDR Tone | +0x08 | 0xFFFFFFFF |
| Cross | +0x10 | 0xFFFFFFFF |

### 18a. Probe round 4 result (photo-ma4, R0011782-89, 2026-10-08) — MultiAxial investigation closed
All six header-mask modes within dE2000 0.8 of Standard (max 7.7 codes, same small non-Standard-mode green dip as before).
No closing Standard shot; the round-4 build has no visible signature, so "flashed" is assumed from the user's report.
Conclusion after 4 rounds: nothing reachable from the tuning data (MultiAxial set fields, CC0CTL, CCA0 header words
0x00/0x04/0x08/0x10) makes the MultiAxial matrices act on stills. Possible remaining causes (not pursued): an enable in a
register the R2Y driver sets outside the tuning image, or the block absent/fused off on this SoC. Selective hue shifts
must be approximated with look matrix + per-channel curves (§11 items 1-3).

## 19. Films v3: warm-hue weighted refits (built 2026-10-08, offline)
`cube_fit.py --boost W --neutral N` adds `warm_samples` (HSV hue 15–90°, sat 0.35–1, 4.5 stops; weight W × chart total)
and `near_neutral_samples` (±8 % channel spread, 8 stops; N × that) so warm hues get priority without tinting neutrals.
Picks (fits in `work/films_v3/fits/`, chosen with `eval_warm.py` and `work/films_v3/regions.py`):

| Film (slot) | fit | warm-set dE v2→v3 | warm hue error v2→v3 | general dE v2→v3 | test2 scene: neutral / warm / other |
|---|---|---|---|---|---|
| Portra 400 (Cross) | b4 n3 | 4.80→3.38 | +6.3°→+2.5° | 3.10→3.30 | 0.79→1.08 / 5.47→4.17 / 2.53→2.48 |
| Gold 200 (Retro) | b4 n3 | 3.88→3.12 | +3.2°→+0.6° | 3.06→3.24 | 0.74→1.09 / 4.87→3.81 / 2.59→2.53 |
| Ektar 100 (Vivid) | b1 n3 | 5.17→4.59 | +5.8°→+4.1° | 3.54→3.53 | 0.92→0.99 / 5.77→5.26 / 3.01→2.99 |
| Pro 400H (HDR, Gold curves) | b2 n3 matrix-only | 3.59→3.22 | +3.7°→+2.5° | 3.40→3.39 | 2.33→2.52 / 4.61→4.18 / 2.66→2.75 |

(+hue error = rendered more yellow than the spektrafilm target.) Costs: neutrals +0.1–0.3 dE, purples/magentas +1–2 dE on
the chart; skin patches improve. Ektar b2+ tints neutrals badly (2.4), so only b1. Without the neutral set (n0), b4 raised
neutral dE to 1.3.
Build: `make_films.py` → `work/films_v3/fwdc239b.bin` (SHA-256 68821c7d…79bef35), `verify_films.py` ALL OK.
Visual: `work/films_v3/compare_v2_v3_target.jpg` (v2 model | v3 model | target, photo-test2 RAWs), `compare_crop.jpg`.

### 19a. Films v3 on camera (photo-ma5, R0011790-96, hue chart, 2026-10-08)
`work/films_v3/check_ma5.py` (Standard model fitted on this shot: dE 0.63; 252 patches, warm = target C>20, hue 30–100°).

| Film | camera vs v3 model | camera vs target (all / warm) | warm hue err camera | v2 model vs target (all / warm, hue) |
|---|---|---|---|---|
| Ektar 100 | 0.53 | 3.51 / 4.40 | −0.8° | 3.52 / 4.90, +0.9° |
| Gold 200 | 0.54 | 3.11 / 3.11 | −3.5° | 2.96 / 3.89, −1.5° |
| Pro 400H | 0.56 | 2.87 / 2.43 | +1.5° | 2.97 / 2.87, +2.6° |
| Portra 400 | 0.53 | 3.06 / 2.91 | 0.0° | 2.89 / 4.28, +3.6° |

The firmware renders exactly what the v3 model predicts (dE ≈ 0.5). Warm colours improve for all four (Portra the most);
overall chart error is ±0.15 of v2. On this chart Gold lands slightly too orange (−3.5°). (− = more orange than target.)

## 20. Films v4: Pro 400H gets its own curves (built 2026-10-08, offline)
Library curves 0–2 were only used by the Cross "random" preset (unreachable once the selector is forced per tone), so
they now hold Pro 400H's own fitted curves. `make_films.py` code patch at the ctx-fill tail (0x536DD454–0x536DD464 +
0x536DD4B8…): `cmp r1,#20`, then movweq/movwne/movt pick library pointers 6–8 = curves 0,1,2 (HDR) or the stock 6,7,8
(Retro's set) and `stm` them to RAM 0x5503761C on every Make. HDR keeps selector 3. Emulated: `verify_films.py` ALL OK,
`work/films_v4/seqcheck.py` (Retro→HDR→Retro→Standard→HDR→Retro in one session, still + LV) curve err ≤1 /16384.
Fit `work/films_v4/fits/pro400h_own_b4n3.json` (`--boost 4 --neutral 3`), others = v3.

| Pro 400H | v3 (Gold curves) | v4 (own curves) |
|---|---|---|
| chart dE | 3.23 | 2.52 |
| general dE | 3.39 | 2.84 |
| warm dE / hue err | 3.22 / +2.5° | 3.04 / +2.5° |
| test2 scene neutral / warm / other | 2.52 / 4.18 / 2.75 | 1.11 / 3.35 / 1.98 |

Output `work/films_v4/fwdc239b.bin` (SHA-256 bfe42f3b…8e79eed). Not yet camera-tested.

Next lever (needs one camera test): a neutral-preserving 3×3 after the curves (gamma domain) would cut warm dE a lot at
equal general dE (`work/films_v4/postgamma_ceiling.py`: warm Portra 3.38→2.26, Gold 3.12→2.51, Ektar 4.59→2.68,
400H 3.04→2.34). Candidate hardware: CCA1 (info+0x1220, after GAM in the R2Y order; 2-bit ctl from ColorMatrix
out+0x30, stock 0 = off; 12-bit coefficients from out+0x32…) or the YCbCrMatrix (hue) block.

## 21. RAW noise reduction (PPU Bayer NR) — films v5 turns it off (built 2026-10-08, offline)
No menu item controls it. The RAW is filtered in the **PPU** (sensor front end: SLVS-EC RX, OBC, DPC/SDPC/DDPC, PDSP,
NR; registers NR_ENABLE 0xA2, NR_NOISE_Y_0..19 0xA4.., NR_NSCALE_*, NR_ALPHA) before the main SoC and the DNG writer.
- Debug-flag object (singleton getter 0x53654150, ctor 0x536533b0 = name table obj+0x204+4i, value obj+0x105+i,
  get 0x53654220, set 0x5365422c only if obj+6+i). Relevant: 0x1F DISABLE_ALL_NR (only dark-frame/long-exposure
  decisions 0x53512bec/0x53512e28), 0x52 DISABLE_ELF_NR (never read), 0x77 DISABLE_PPU_NR, 0x7C DISABLE_PPU_NR_PARAM,
  0xA5 DISABLE_PPU_ALL. All stock 0.
- Still FE setup 0x53434040 → 0x5343322c: out+0x64 = NR unit on = !cfgsrc[1] (0 if flag 0x77), out+0x69 = NR param
  on = !cfgsrc[4] (0 if 0x7C); cfgsrc = obj+0x60, a runtime message payload (handler 0x5342da10). Siblings: out+0x66
  SDPC, +0x67 DDPC, +0x68 PDSP. The PPU config cfg = out+0x50.
- PPU start 0x53642e78: enable mask bit0 always, bit1 cfg+0x16, bit2 +0x17, **bit3 = NR (cfg+0x14)**, bit4 +0x18 (0x20
  only if DISABLE_PPU_ALL) → driver 0x5380cc04. Alternate path 0x53642a84 sets bit 3 from cfg+2.
- NR parameters 0x53642b24 → NRUnit 0x536edbbc: p[0] = ISO index cfg+0x2c (= 8·(Sv−1); ISO100 = 32, 200 = 40,
  800 = 56, 3200 = 72, 6400 = 80, 25600 = 96), p[1] = mode 0 if cfg+0x19 else 3. Tables (RAM 0x550375AC..FC → ROM
  0x53EF12C4..0x53EFA33C, 12-byte A + 20-byte B entries × 144 ISO steps, 2 variants): mode 0 B enable from index 36
  (ISO ~140), strength byte 8 @ISO200, 0x18 @400, 0x20 from 800, level 0→3 at ISO ~1100/3200/12800; mode 3 never
  enabled. Live view (0x5343f2ec) uses modes 1/2.
- Patch (`raw_nr.py`, `make_films.py --raw-nr-off`): 0x5343326C/0x53433284 `eoreq` → `mov r6/r7,#0` (as if flags
  0x77/0x7C were set: unit off, params mode 3) and 0x53642AC4 `orrne r4,r3,#0x18` → `#0x10`. Emulated 0x5343322c:
  stock out(0x64,0x69) = (1,1) for cfgsrc 0 → v5 (0,0). Live view and JPEG NR (R2Y YNR / CNR) untouched.
- Measured (`raw_noise.py`, lag-1 correlation of flat-area noise above white noise): photo-test2 ISO 200 +0.016
  (≈ a 3×3 blur blended in at ~7%, or leftover texture); no high-ISO RAWs yet.
- Output `work/films_v5/fwdc239b.bin` (v4 + the 3 words; SHA-256 72ff8532…65d865), `verify_films.py` ALL OK.
  Not camera-tested; test = dark frames + defocused grey at ISO 200/1600/6400/25600 before/after
  (`work/films_v5/HOW_TO_SHOOT.txt`).

### 21a. Camera test 1 (photo-nr1, 2026-10-08): v5 removes most of the RAW NR
One ISO 25600 shot each of the same floor scene at equal exposure (A stock-NR 1/30 f/3.2, B v5 1/10 f/5.6; black 4032).
Green-plane noise SD in matched-brightness flat blocks: 147→259 (mean 0–60), 167→281 (60–150), 219→333 (150–400),
i.e. +60–75 % noise = the stock RAW was strongly denoised at ISO 25600 and v5 turns it off. Lag-1 excess 0.10→0.075
(not 0): could be texture of the wood floor (horizontal lag 0.107 vs vertical 0.058 in B) or another stage; needs flat
targets (dark frame / defocused grey) to tell. Lower ISOs not tested yet.

### 21b. Films v6: RAW NR only at ISO ≥ 6400 (built 2026-10-08, offline)
`make_films.py --raw-nr-from-6400` (`raw_nr.patch_raw_nr_min_iso`): clears the enable byte (B[0]) of the mode-0 B
entries for ISO index 36..79 in both variants (ROM 0x53EF6868 / 0x53EF9720, 88 bytes), so ISO 140..5000 get the same
"NR off" parameters stock already uses at ISO ≤ 125; ISO ≥ 6400 entries untouched. No code change. Emulated NRUnit
(v4 → v6 B flags): ISO 200 1→0, 800 1→0, 1600 257→256, 3200 257→256, 5000 513→512, 6400/12800/25600 unchanged
(513/513/769). Level bits without the enable bit also occur in stock (mode 2). Mask bit 3 (NR unit) stays on, as at
stock ISO 100. `verify_films.py` ALL OK. Output `work/films_v6/fwdc239b.bin` (SHA-256 30711e24…c8ea25).
Not camera-tested.
Camera test (photo-nr2, ISO 5000, v4 1/80 vs v6 1/100 f/3.2, black 2048): RAW noise SD in matched flat blocks
G 43→60 / 55→80 / 115→162, R 21→60 / 33→82 / 76→143, B 20→57 / 30→87 / 56→124; lag-1 excess R/B +0.13–0.17 →
+0.03–0.05, G +0.06–0.09 → +0.04. So stock smooths R/B (chroma) about 3× harder than G, and v6 removes it at ISO 5000.
JPEG: finer grain + more wood texture in v6 (`work/films_v6/compare_iso5000_crop.jpg`). ISO ≥ 6400 not shot (table unchanged).

### 21c. Films v7: RAW NR only above ISO 8000 (built 2026-10-08, offline)
`make_films.py --raw-nr-above 8000` (`raw_nr.above_index`: midway to the next 1/3 stop, so 8000 = idx 82.7 off,
10000 = 85.3 on → first kept index 84). Clears B[0] for index 36..83 (96 bytes). Emulated NRUnit B flags v4 → v7:
ISO 200 1→0, 5000/6400/8000 513→512, 10000/12800 513 = 513, 25600 769 = 769. `verify_films.py` ALL OK; v6 still
rebuilds bit-identical. Output `work/films_v7/fwdc239b.bin` (SHA-256 a7d60c88…7889b7). Not camera-tested
(same mechanism as v6, confirmed at ISO 5000).

## 22. Factory / engineering menu entry (static, 2026-10-08, not yet tried on camera)

Same mechanism as the camera-verified GR IV and GR IIIx 1.60 (`~/dev/ricoh-gr4-firmware-analysis-and-feature-expansion`):
- Entry file name: 0x536bdc44 / 0x536be854 sprintf `C:\%08ld.%03ld` (0x53d615d8) with 0x5381fe9c = 0x1320E (78350) and
  0x5381fe4c = 0x24C (588) -> **`C:\00078350.588`** (GR IIIx 1.60: 00078490.609, GR IV: 00078560.636).
- Key file: name XOR 0x29 at 0x538f2d84 -> `C:\DEVELOP.MOD`; must be 10 bytes (0x536bf744) equal to key 1
  `07 01 2c 1f 10 03 1e 16 05 2d` (0x53d628a0, mode 1) or key 2 `07 1a 02 0a 19 18 1b 1c 05 11` (0x53d628ac, mode 2).
- Entry file parser 0x536be854: CR-terminated lines, `!`/`;` comments, commands in `[...]`, matched by 0x536bdd80 against the
  0x20-byte table at 0x538f2d94..: DEBUG_MODE EN/DIS, WRITE_CF_VNDR EN/DIS, SCRIPT_EN_MODE EN/DIS, SW_DEBUG_MENU EN/DIS,
  USR_DAT_CLEAR, OPEN_DEBUG_MENU, OPEN_FACTORY_DEBUG_MENU, SWITCH_TEST, RELEASE_AGING, DSP_ROM_STORE, ADJ_DAT_READ/WRITE,
  USR_DAT_READ/WRITE, CAM_LOG_DAT_READ, CAM_LOG_DISP, USR_CLEAR_CAM_DISP, RELEASE_COUNT 0/10/25/50/100, INFORMATION, DEBUG_LOG_RE..
- Menu pages (0x53b21b00..): FW Setting1/2, Setting & Display, Test Display, WLAN / BLE, Camera -> SD, SD -> Camera,
  Screen Shot, Factory Menu, Service Menu. Items include Camera Mode, Script, Key Emulate, Serial Input, Store Debug Log,
  Read/Write Adjust Data, Clear User Data, Set Release Count, Store DSP ROM, Display Camera Info, versions.
- Ready-made files: `work/factory_entry/` (00078350.588 = `[OPEN_FACTORY_DEBUG_MENU]\r\n`, DEVELOP.MOD = key 1).
  Use: copy both to the SD root, hold MENU while switching on (GR IV / IIIx procedure).

### 22a. Camera result (factory-mode/, 2026-10-08): entry works on GR III 2.10
- MENU + power with the §22 files opened the factory menu. User set Camera Mode = Debug, ran Read Adjust Data / camera log,
  shot one photo. Card got KB588.ADJ (this body's calibration backup, ~5 MB, includes the serial number - never publish),
  KB588.CAM (usage counters: release/shutter/power-on/aperture/ND counts, lens error log, firmware versions),
  KB588.DOM (APData00-04 user settings), log0.txt (mostly "log buffer overflowed"). File contents stay off the repo.
- Debug mode adds nothing to the JPEG/DNG (same EXIF/MakerNote tag set; APP7 "RICOH" = 720x480 preview).
- Every boot logs "NOT ADJUSTED ... DEFECT PIXEL DATA" and "wlan and ble control is disabled by adjust data" although the ADJ
  file has its defect-pixel entries (HwPxDfct/SwPxDf*/ZAfDPx*) flagged valid (a55a5aa5). Meaning unverified.

### 22b. Script setting (static)
- Script = Enable: start-up runs `C:\script\startup.ttl` ("start script file is found!!"), power-off runs
  `C:\script\shutdown.ttl`; table 0x540b4c38 also has `C:\script\dbgparam.ttl`. Runner 0x536bbe98 needs obj+0xb0 (enable).
- Interpreter = Tera Term Language subset (keyword ids 0x538c3444, executor switch 0x538c1560): file/folder ops, strings,
  if/while/for/goto/call/include, mpause, random, messagebox, sendln, execcmnd. No wait/connect.
- `sendln` (id 0x4e, 0x538c06ac) calls callback [0x5537e9f0] = 0x536bae2c (set from RAM 0x55018bb4 by 0x538bc6ac), the
  engineering shell line parser ("Shell can't be used in Interrupt."). So scripts can run the 585 SHELLCMD commands
  (names/handlers: SHELLCMD section, list in scratchpad shellcmd.txt): camctl_* (shutter/aperture/ISO/bulb timer/capture/
  interval/multiexp), SW_* button emulation (SwS/SwR half/full press, mode dial, menu...), SYS_md (memory dump to file),
  SYS_reg (get/set register), sys_fwdump, SYS_copylog, med_* file ops, focus_*, CAP_REG_* register dumps, dd_* (adjust
  data save/load - dangerous), lcmd (Linux command). Exact argument syntax unverified on camera.
- Probe: `work/script_probe1/script/startup.ttl` (read-only: marker file, SYS_buildinfo, three SYS_md dumps, SYS_copylog).

### 22c. SpecialFeatureFlag 1-16 (adjust data group 0x23, ids 0x82-0x91, SpFFlg01-16) are unused in fw 2.10
- Objects: classes SpecialFeatureFlag1..16 (vtables 0x53d180b8 + 0x58*k), ctors 0x5353a890 + 0x44*k, statics
  0x55345cd8 / 0x55346ed8.. created by AdjustManager init 0x5352909c into its table at this+4+4*id (emulated: +0x20c..+0x248).
  Each holds a 16-byte record: [0] = a55a5aa5 valid / ffffffff unset, [1] = 32-bit value. User's camera: all unset.
- Consumers read adjust items as `bl 0x53525d5c; ldr rT,[r0,#4]; ldr rX,[rT,#4*(id+1)]`. A scan of all 2107 callers finds
  readers for ids 2,3,4,5,6,17-20,31,38-44,60,80,100-111,146,147,179,180,232 but none for 0x82-0x91; no other code builds
  those ids (only the ctors), and the 9 callers of the generic getter 0x53527514 use ids 2 and 0x14. So the flags are only
  touched by generic load/save (factory Read/Write Adjust Data). Reserved for other models/editions; setting them does nothing.
- Edition (shell `collab off/street/urban/ing/diary`, menu "Collab") and lens filter type (ND/HDF, menu "Set Lens Filter
  Type") are separate settings, not these flags.

### 22d. Probe 1 v2 (built 2026-10-08, not yet run) and what it needs
- CAP_REG_B2Y / CAP_REG_IIP / CAP_Lut / CAP_REG_DMA are stubbed in this build (`mov r0,#0; bx lr`, 25 such commands), so
  R2Y registers must be read from RAM with SYS_md. SYS_md 0x53041e50: `<addr> -s <size> -f <file>` writes raw memory to a
  file via 0x536bb174 (log "Dump memory to %s : OK/NG").
- MMU table 0x53004000 (TTBR0): flat 1:1 map; 0x55000000-0x80000000 normal memory. RW data 0x55000000 (+0x3a080 from ROM
  0x5407b540), bss 0x5503a100-0x55804374, heap after that (code references cluster up to 0x55900000).
- Probe (`work/script_probe1/`): stage 0 = marker, SYS_buildinfo, 3 small dumps, SYS_mplt/SYS_mpft, RAM 0x55000000+8 MB;
  90 s pause (user shoots one photo if the camera is usable); stage 1 = 4 x 16 MB heap dumps 0x55810000-0x59810000,
  SYS_copylog. Progress files P1_*.TXT show where it stopped. Analysis plan: find the ImageTuningStill object (vtable
  0x53DBD8A0) and the info block (R2Y image at info+0x120, CCA1 at info+0x1220) by pointer chase / emulated signatures.

### 22e. Probe 1 result (script-probe1/, v7 firmware, 2026-10-08): scripts + engineering shell work
- Stage 0 completed: P1_NAME.BIN = `C:\%08ld.%03ld` + following ROM strings (exact), so `sendln 'SYS_md ...'` runs the
  shell command and writes raw memory to the card. Camera reached the shooting screen normally (script runs async).
- P1_BTAB.BIN (live NRUnit mode-0 B table, variant 0) has enable 0 for index 0-83 and 1 from 84 = v7 exactly
  (P1_BPTR = 0x53EF9720 / 0x53EF6868 as expected). **v7 RAW NR cutoff confirmed in the running camera.**
- P1_RAM0.BIN (0x55000000 +8 MB): RW data matches the ROM image except 337 words. No ImageTuning vtable in it (heap object,
  created by 0x536f0304 -> owner+4). Heap pointers in it cluster at 0x570-0x573xxxxx and 0x591-0x59Cxxxxx.
- Stage 1 never started (no P1_S1GO.TXT): either the camera was switched off within 90 s of the stage-0 dumps, or the
  script stops later (mpause / mode change). Probe 2 adds 10 s heartbeats and dumps 0x55000000-0x56F00000 (via 2 files),
  0x56F00000-0x58000000, 0x58800000-0x59E00000 at t = 60 s.

### 22f. Probe 2 result (script-probe2/, v7, R0011827 Vivid ISO 5000, 2026-10-08): live R2Y block read back
- Script stays alive the whole time (15 heartbeats over 150 s) while the camera is used normally. P2LOG not created
  (SYS_copylog path form wrong or not supported); everything else OK.
- ImageTuningStill object at 0x5966b440 (LV object 0x5966b680). Still info blocks found by the emulated Vivid CCA0
  matrix: 0x599aa6a0 (stage byte 1, SI 0x70d48800) and 4 identical copies (0x5972e3e0, 0x597476d0, 0x59929ba0,
  0x599e30d0). **info+0x100..0x11DF (CCA0 matrix, Y-blend, MultiAxial) equal the emulation byte for byte** -> the film
  look in the camera is exactly what verify_films checks. Differences only where run_tuning stubs or ignores inputs
  (+0x11e0 block, gamma/tone tables from +0x1688 etc.: DR auto, shadow correction, ISO 5000).
- CCA1: info+0x1220 ctl = 0, coefficients info+0x1240.. = identity 0x200 (rows at +0x1240/+0x1246/+0x124c), clip
  0xfff at +0x1260. Coefficients come only from ColorMatrix init 0x536DED70 (`strh` of 0x200 to out+0x32/0x3a/0x42,
  0 elsewhere); Make never changes them; writer 0x536DF13C copies out+0x30 (2-bit ctl) and out+0x32..0x42 (12-bit) to
  info+0x1220/0x1240 every shot. By analogy with CC0CTL (0 = x0.5), ctl 0 with 0x200 = unity, i.e. CCA1 is probably
  active as an identity.
- `make_cca1_probe.py` -> `work/cca1_probe/fwdc239b.bin` (SHA-256 7050586f…fc290d) = v7 + 4 strh changes in the init
  (rows (0,0,1)(0,1,0)(1,0,0)). Emulated: only info+0x1240/44/4c/50 change for tones 11/12/19/20/21; RTOS differs from
  v7 in 4 bytes. Plus `work/cca1_probe/script` (probe 3 = probe 2 with P3_ names) for read-back. Not yet flashed.

### 22g. CCA1 is live (photo-cca1, R0011831, 2026-10-08) -> films v8 warm-colour fix (built, not yet camera-tested)
- cca1_probe (rows (0,0,1)(0,1,0)(1,0,0)): camera JPEG shows red and blue exchanged (yellow -> cyan, orange -> blue,
  navy -> brown, purple -> pink), also in live view. Channel correlation JPEG vs DNG render: JPEG R ~ DNG B (0.965),
  JPEG B ~ DNG R (0.975). So CCA1 is an active RGB 3x3 after GAM (the film curves), ctl 0 with 0x200 = 1.0; coefficients
  are 12-bit two's complement (the writer masks with bfi #0xc).
- `cca1_fit.py` (= postgamma_ceiling objective, neutral-preserving rows rounded to sum 512) -> work/films_v8/cca1_mats.json:

| Film | CCA1 (x/512) | warm dE before -> after | general dE |
|---|---|---|---|
| Ektar (Vivid) | [519 21 -28; 29 429 54; -7 20 499] | 4.59 -> 2.68 | 3.53 -> 3.54 |
| Gold (Retro) | [523 2 -13; 24 457 31; -4 19 497] | 3.12 -> 2.51 | 3.24 -> 3.30 |
| Pro 400H (HDR) | [506 30 -24; 14 480 18; -6 32 486] | 3.04 -> 2.33 | 2.84 -> 2.71 |
| Portra (Cross) | [509 29 -26; 26 453 33; 4 8 500] | 3.38 -> 2.27 | 3.30 -> 3.42 |

- `cca1.py` + `make_films.py --cca1 mats.json`: ColorMatrix Make wrapper `bl calc` (0x536DF3E8) -> stub 0x536EF61C that
  looks up the look record [ctx+8] (0x550196D8 / 0x55019108 / 0x55019060 / 0x5501939C) in a table and copies the film's
  9 coefficients (identity for any other record) to obj+0x32, then `b calc`. Stub + table (188 B) sit in the Cross
  "random" preset branch; 0x536EF618 becomes `b 0x536EF6DC` (fixed-preset case) so that branch is dead.
- `work/films_v8/fwdc239b.bin` (SHA-256 150fe1098746b644149b47818e43a7db776e22ae2f44a7096f0d5acff44e7727) = v7 flags +
  --cca1. `verify_cca1.py v7 v8 mats`: still and LV over a 13-tone sequence, R2Y identical to v7 except info+0x1240..51 =
  film matrix / identity, ctl 0 -> ALL OK. verify_films ALL OK.

### 22h. Films v8 on camera (photo-v8, R0011832-43, 2026-10-08): CCA1 fix works as modelled
`work/films_v8/check_v8.py` (chart.py finds the 4 corner markers, so camera movement is tolerated; Standard model fit on
R0011833: dE 0.70; WB was Multi Auto). Camera JPEG vs model: v8 model (curves + CCA1) fits 2x better than v7's.

| Film | camera vs v8 / v7 model | camera vs target all / warm | warm hue err | v8 model warm (v7 model) |
|---|---|---|---|---|
| Ektar (Vivid) | 1.12 / 2.43 | 4.07 / 3.59 | -0.3° | 2.85 (4.72) |
| Gold (Retro) | 0.84 / 1.60 | 3.42 / 2.75 | -1.5° | 2.44 (3.28) |
| Pro 400H (HDR) | 0.85 / 1.46 | 2.87 / 2.51 | +0.9° | 2.05 (2.90) |
| Portra (Cross) | 0.89 / 1.64 | 3.61 / 2.59 | -0.4° | 2.21 (3.21) |

Warm colours (target C>20, hue 30-100°) on camera: Ektar 3.59 (v3 chart test: 4.40), Gold 2.75 (3.11), Portra 2.59 (2.91).
Overall model error +0.05..0.2 (fit objective trades a little general accuracy).
Hand shots (`hand_compare.py`, R0011842 Ektar / R0011843 Portra, forearm patch, Lab): v8 moves skin only slightly
(hue +0.7..1.1°, chroma ±0.3 vs v7 simulated by undoing CCA1). The spektrafilm target rendered from the DNG is
~5-6° yellower and 3-6 chroma richer on skin (Ektar 53.6°/22.3 vs 48.9°/16.6; Portra 54.6°/18.3 vs 49.1°/15.1): skin
(C~15) is below the warm-set chroma cut (C>20), so the CCA1 fit barely weighted it. Next lever: skin-weighted refit.

### 22i. Films v9: joint refit of look matrix + curves + CCA1 (built 2026-10-08, not yet camera-tested)
v8 only added CCA1 on top of fixed v3/v4 fits. `joint_fit.py` alternates CCA1 (LS), curves (fit to target pulled back
through CCA1^-1) and look matrix, 6 rounds, same samples/weights as the original fits, CCA1 rounded to x/512 and curves
refitted against it. Fits: work/films_v9/fits/*_joint.json (with `cca1_q512`), mats work/films_v9/cca1_mats.json.

| Film | general dE v7 -> v9 | ColorChecker | warm | CCA1 (x/512) |
|---|---|---|---|---|
| Ektar | 3.53 -> 2.77 | 3.25 -> 1.79 | 4.59 -> 2.38 | [512 35 -35; 35 406 71; 12 59 441] |
| Gold | 3.24 -> 2.48 | 2.62 -> 1.61 | 3.12 -> 1.91 | [541 -7 -22; 42 406 64; 6 56 450] |
| Pro 400H | 2.84 -> 2.42 | 2.52 -> 1.62 | 3.04 -> 2.09 | [504 55 -47; 33 449 30; 1 76 435] |
| Portra | 3.30 -> 2.58 | 2.86 -> 1.65 | 3.38 -> 1.96 | [513 40 -41; 38 409 65; 14 49 449] |

Prediction on the real photo-v8 chart patches (`work/films_v9/predict_v9.py`, model vs target): Ektar 3.46 -> 2.65,
Gold 3.07 -> 2.19, 400H 2.54 -> 2.05, Portra 3.25 -> 2.31 (v8 -> v9). Forearm: hue Ektar 48.1 -> 51.1° (target 53.7),
Portra 49.6 -> 52.6° (54.5), chroma unchanged (target richer).
`work/films_v9/fwdc239b.bin` SHA-256 0bc9c8eb63f94034d8d611207c32f416944a702692f40fb95563ab819624d28b
(make_films --raw-nr-above 8000 --cca1 work/films_v9/cca1_mats.json + joint fits). verify_films ALL OK, verify_cca1 (vs
the same build without --cca1) ALL OK.

### 22j. photo-v9 (R0011848-55, Daylight WB, 2026-10-08): the camera rendered v8, not v9
`work/films_v9/check_v9.py`: camera vs v9 model dE 1.73-1.83 with a consistent green/light offset (da -1.1..-2.0), worse
than vs the v8 model (Ektar 1.57, Portra 1.47). Regressing (camera - v9 model) on (v8 model - v9 model) per channel gives
slope 0.88-1.10, corr 0.72-0.81 for all four films -> the shots were taken on v8 firmware (flash not applied / wrong file).
Camera vs target on these Daylight-WB shots (v8 rendering): Ektar 3.64, Gold 3.20, 400H 2.90, Portra 3.17.
`work/fw_check/script/startup.ttl` dumps 0x536EF618 +0x120 (stub + CCA1 table) to C:\FW_CCA1.BIN; compare with
work/fw_check/expect_v8.bin / expect_v9.bin to identify the running build.

### 22k. photo-v9 rerun (R0011856-62) + FW_CCA1.BIN: v9 IS running; gap is only on extreme colours
FW_CCA1.BIN (fw_check script, RAM 0x536EF618 +0x120) == expect_v9.bin byte for byte, so §22j's "camera rendered v8" was
wrong. The camera-vs-model gap (dE ~1.8) sits almost entirely in chart rows 0-1 (full-brightness, saturation 1.0/0.6
monitor colours): camera brighter and less red there (dL +3, da -4..-5), i.e. a saturation/gamut compression the model
lacks; no free post- or pre-matrix refit removes it (stays ~1.7). On rows 2-6 (normal colours) camera vs target:
v8 -> v9 Ektar 3.38 -> 2.73, Gold 2.95 -> 2.51, 400H 2.42 -> 2.40, Portra 3.05 -> 2.42 (v9 model predicts 2.52/2.16/2.06/2.13).
Open: model the high-chroma compression (e.g. CCA0 Y-dependent blend / clipping) so fits stop over-pushing saturated colours.

### 22l. CCA1 acts BEFORE the gamma curves -> films v10 (post matrix via the YCbCr matrix, + 5th film)
The §22k "high-chroma compression" is not a missing stage: CCA1 is applied in the linear domain right after CCA0, i.e.
camera = curves(base(C M L)), not clip(curves(base(M L)) C). With that model, camera vs model on the hue chart drops
from 0.93 -> 0.58 (v8) and 1.81 -> 0.61 (v9) mean dE over all four films, the same as the Standard model's own floor
(0.64); every chart row fits (rows 0-1 4.5/3.7 -> ~0.6). Rejected alternatives: CCA1 before the film curves but after
base gamma (1.74), CCA1 in a power-gamma domain (best 1.5), transposed (4.5-9), free post 3x3 (1.7), Y taken from a
separate Y gamma path (2.5). The R/B swap probe (§22g) could not tell linear from post-gamma (a permutation commutes with
per-channel curves of equal shape). So CCA1 is just another linear 3x3 and gives nothing beyond the look matrix.

A real post-gamma 3x3 does exist: the CSP (RGB->YCbCr) matrix, info+0x1180, 9 x 9-bit two's complement, 256 = 1.0,
stock BT.601 (77,150,29 / -43,-85,128 / 128,-107,-21), rotated in Cb/Cr by the Hue parameter (SI+0x77E: hue 0 ->
(-20,-102,122 / 134,-92,-43)). Written by YCbCrMatrix Make 0x536E4760 from obj[0..8] (19-bit two's complement) after its
calc 0x536E4720; [ctx+8] is the look record there too. JPEG decoding inverts BT.601, so H P in the CSP = P applied to
gamma-encoded RGB = exactly what the v8/v9 joint fits assumed.

Free code space, corrected: the Cross "random" case of 0x536EF148 (jump-table entry 0) is 0x536EF618..0x536EF6D8 plus
0x536EF6FC..0x536EF994; 0x536EF6DC..0x536EF6F8 is the LIVE fixed-preset case (entries 1-3). cca1.py's CAVE_END
0x536EF998 was wrong; its v8/v9 blob (188 B) ended at 0x536EF6D8 by luck. A 5th film needs 3 more 256-entry curves
and there is no 1.5 KB of provably free storage, so its curves are stored as 33 knots (step 8, max 34/16384 off the
fit) and expanded at run time into g+0xA08 (packed gamma tables, rewritten from the composite later in the same call).

Films v10 (`film_cave.py`, `make_films10.py`, `armasm.py` = llvm-mc wrapper; `verify_films10.py` ALL OK):
* CSP stub (bl from 0x536E4774): runs the calc, then for a film record replaces H by round(H P/512); hue still works.
* ctx fill tail 0x536DD454 -> cave fill: library slots 6..11 per tone (stock / HDR curves 0-2 / Bleach knot tables),
  selector 12,18 -> 4, 19,20 -> 3, 21 -> 2; the three pointer sets live in the old chain area 0x536DD4B8.
* curve getter call 0x536E87C4 -> stub that expands knot-table pointers into the scratch buffer.
* Bleach Bypass (tone 18, variant slots 22/23 via SI+0x786) -> Kodak Vision3 250D on Kodak 2383 print, own record
  0x55018F94 (copy of the Standard record, Bleach matrix 0x53DC2474 refitted; drops Bleach's toning offset at
  info+0x1674), name "Vision3 250D" (string 0x113), icon "250D" (0x15A). Fit: chart 2.88 -> 1.94 after joint fit,
  Standard vs target 5.8.
* CCA1 stock (identity). Emulated: Standard/mono/Positive/Negative byte-identical to stock (still + LV); every film's
  composite = fitted curves (+-1), CSP = H(hue) P for hue 0/4/8, R2Y vs Standard differs only in CCA0, CSP, gamma.
* Prediction on the photo-v9 chart (all patches, camera v9 -> v10 model): Ektar 3.64 -> 2.62, Gold 3.20 -> 2.20,
  400H 2.91 -> 2.09, Portra 3.14 -> 2.24; Vision3 250D 2.58.
`work/films_v10/fwdc239b.bin` SHA-256 88adfd79d948d6b2e7f023d5e63462309fe9ea7ae8e2a0378838c5c8b25f45e4, RAW NR above
ISO 8000 as v7. `work/films_v10/script` dumps 0x536EF618 +0x380 to C:\FW_V10.BIN (compare work/fw_check/expect_v10.bin).
Not yet camera-tested.

### 22m. Films v10 on camera (photo-v10, R0011890-97, 2026-10-08) -> v11 perceptual refit
v10 renders exactly as modelled: camera vs v10 model (curves, then P via the CSP) dE 0.80 / 0.57 / 0.60 / 0.54 / 0.55
(Ektar/Gold/400H/Portra/Vision3 250D), every chart row 0.4-1.3 (§22l model confirmed). Camera vs target (all 252 patches):
| film | v9 camera | v10 camera |
|---|---|---|
| Ektar 100 | 3.64 | 2.81 |
| Gold 200 | 3.20 | 2.22 |
| Pro 400H | 2.91 | 2.08 |
| Portra 400 | 3.14 | 2.28 |
| Vision3 250D | - | 2.49 |
(`work/films_v10/check_v10.py`.) Residual model-vs-target is mostly chroma: |dC| ~4 vs |dL| ~1, with a systematic
deficit (mean dC -2.1..-2.5): the RGB least squares of cube_fit/joint_fit under-saturates. Headroom test of extra
YCbCr stages on top of the v10 model (RGB-LS fitted): Y-dependent saturation / Cb,Cr offsets / per-hue gain+rotation
(ideal MultiAxial) gain only 0-0.2 on the camera chart -> not worth more RE now.
`lab_fit.py`: same parameters (look matrix, post matrix, curves + 17-knot corrections) refitted on per-sample dE2000.
general / warm / ColorChecker / camera chart (held out), before -> after:
Ektar 2.77/2.38/1.79/2.63 -> 2.32/1.95/1.65/2.30; Gold 2.48/1.91/1.61/2.21 -> 2.10/1.58/1.39/1.87;
400H 2.42/2.09/1.62/2.13 -> 2.07/1.50/1.46/1.95; Portra 2.58/1.96/1.65/2.28 -> 2.14/1.66/1.45/1.98;
Vision3 250D 2.34/2.00/1.94/2.60 -> 2.13/1.66/1.74/2.42. Greys unchanged (dE76 <= 0.67; 250D 1.24 -> 0.55).
Films v11 = make_films10.py with the work/films_v11/fits/*_lab.json fits: SHA-256
90691ea19c205c0740221537c3d4972d826433a5230baf09b88157238c1b48ae, verify_films10 ALL OK, fw check expect_v11.bin
(FW_V11.BIN via work/films_v11/script). Not yet camera-tested.
