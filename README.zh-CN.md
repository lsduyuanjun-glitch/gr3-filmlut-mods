# GR III 固件 2.10 图像管线逆向工具

[English](README.md) | **简体中文**

为理光 GR III 固件 2.10 制作的自定义胶片风格（Kodak Ektar 100、Gold 200、Portra 400、Fujifilm Pro 400H、
Kodak Vision3 250D）以及 RAW 降噪修改，全部通过离线修补官方升级文件实现。研究笔记见 `FINDINGS.md`（英文）。

## 改动内容（胶片 v10 / v11 版本）

| 原图像控制模式 | 改为 | 胶片目标（spektrafilm） |
| --- | --- | --- |
| 鲜艳 | Ektar 100 | Kodak Ektar 100 + Portra Endura 相纸 |
| 复古 | Gold 200 | Kodak Gold 200 + Portra Endura 相纸 |
| HDR 色调 | Pro 400H | Fujifilm Pro 400H + Crystal Archive 相纸 |
| 交叉冲洗 | Portra 400 | Kodak Portra 400 + Portra Endura 相纸 |
| 漂白效果 | Vision3 250D | Kodak Vision3 250D + Kodak 2383 拷贝片 |

* 每种胶片都有独立的风格矩阵、独立的 R/G/B 色调曲线，以及一个伽马后的 3x3 色彩矩阵（通过相机的 RGB->YCbCr
  环节实现，因此"色相"调节仍然有效）。模式名称和图标在全部 21 种界面语言中都已替换。
* 这些模式关闭了 HDR 色调原有的局部色调映射和复古模式的暗角。
* ISO 8000 及以下关闭 RAW（Bayer）降噪（更高 ISO 保持原厂行为）。JPEG 高感降噪不受影响。
* 标准、单色、柔和单色、硬调单色、高对比黑白、正片、负片与原厂逐字节一致。

## 当前精度

相机 JPEG 与 spektrafilm 目标之间的平均 ΔE2000（越低越好），使用相机实拍的 252 色块色相图（ISO 200，日光白平衡）。
"标准"一列是未修改的标准模式与同一目标的差距，作为参照；ΔE ≈ 1 大约是人眼刚能察觉的差异。

| 胶片 | 标准 vs 目标 | v9（实机） | v10（实机） | v11（预测） |
| --- | --- | --- | --- | --- |
| Ektar 100 | 6.80 | 3.64 | 2.81 | 2.30 |
| Gold 200 | 6.05 | 3.20 | 2.22 | 1.87 |
| Pro 400H | 4.48 | 2.91 | 2.08 | 1.95 |
| Portra 400 | 6.36 | 3.14 | 2.28 | 1.98 |
| Vision3 250D | 6.59 | – | 2.49 | 2.42 |

模型对相机的预测误差在 ΔE 0.55–0.8 之内，因此 v11 的数字应当可信，但 v11 尚未实机测试。
剩余误差主要来自饱和度；详见 `FINDINGS.md` §22l–§22m。

**不包含：** 任何理光固件、修补后的固件镜像或照片。你需要自备 `fwdc239b.bin`（2.10 版）。
固件容器编解码器（`gr4_editor`）来自 [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool)
（GPL-2.0），以随仓库分发（vendored）的形式放在 `third_party/gr-custom-tool`（保持其自身的 GPL-2.0 许可，
不在本仓库许可范围内）。如需使用其他副本，可设置环境变量 `GR_CUSTOM_TOOL`。

> [!WARNING]
> **免责声明 —— 一切风险由使用者自行承担。** 本项目是非官方的逆向工程研究。刷入修改过的固件存在风险：
> 可能导致相机永久变砖、硬件损坏、照片或设置损坏，并且几乎必然使保修及厂商支持失效。这些补丁仅经过离线
> 仿真验证，并只在一台相机上测试过；无法保证它们在你的相机上可用或安全。对于因使用本仓库任何内容而造成的
> 任何损坏、数据丢失、相机变砖或损坏，以及任何其他后果，作者**不承担任何责任**。如果你不能接受失去这台相机，
> 请不要刷机。
> 本项目与理光映像（Ricoh Imaging）无任何关联，未获其认可或支持；文中产品名称均为其各自所有者的商标。
> 软件按"原样"提供，不附带任何形式的担保（见 `LICENSE`）。
>
> 如中英文版本有出入，以英文版 `README.md` 为准。

胶片目标效果由 [spektrafilm](https://github.com/andreavolpato/spektrafilm) 的 LUT 渲染；富士 Classic Neg 除外，
它拟合的是 [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles) 中的
`classic neg_sRGB.cube`。`work/**/fits` 中拟合出的曲线和矩阵源自这些 LUT。

许可（按部分）：
* 代码和笔记：**GPL-2.0**（`LICENSE`）。版权（C）2026 idontknownihil 与 Duccio（杜沅骏）。
  本项目基于 idontknownihil 的 GR III 逆向工作，并与 [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool)
  （GPL-2.0）及 Unicorn（GPLv2）链接，因此整体以 GPL-2.0 分发。
* 源自 spektrafilm LUT 的拟合数据：`work/**/fits/` 中除 `classicneg_*` 以外的全部文件，以及 `work/films/*.json`、
  `work/portra400/portra_fit.json`、`work/films_v8/cca1_mats.json`、`work/films_v9/cca1_mats.json`。源自
  Andrea Volpato 的 [spektrafilm](https://github.com/andreavolpato/spektrafilm)，采用 CC BY-SA 4.0 许可（spektrafilm
  许可及 CC BY-SA 4.0 全文见 `LICENSES/SPEKTRAFILM_LICENSE.txt`）。由 idontknownihil 修改：将这些 LUT 拟合为
  GR III 相机参数（见 `LICENSES/CHANGELOG.txt`）；本仓库不包含 LUT 本身。改编作品须保持 CC BY-SA 4.0 并保留此署名。
* 源自 FujifilmCameraProfiles LUT 的拟合数据（`work/**/fits/classicneg_*`，即 `spec` 指向该仓库的所有拟合）：
  [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)（全文见 `LICENSES/CC-BY-NC-SA-4.0.txt`）。
  署名：改编自 abpy 的 `classic neg_sRGB.cube`，
  [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles)，CC BY-NC-SA 4.0。修改内容：将该 LUT
  拟合为 GR III 的外观矩阵、色调曲线和曲线后矩阵；本仓库不包含 LUT 本身。按"原样"提供，不附带任何担保（见许可第 5 节）。
  仅限非商业用途，改编作品须以相同许可共享。用这些拟合数据生成的固件镜像同样适用：不得出售或用于商业分发。
* `third_party/gr-custom-tool`：GPL-2.0（见其自带的 `LICENSE`）。

仅限离线使用。输入文件：`../fwdc239b.bin`（SHA-256 `d6a3c9c2…54bfd4`）。所有地址仅对该文件有效。

环境准备（Python 3.12）：

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

| 文件 | 用途 |
| --- | --- |
| `codec_path.py` | 把 gr-custom-tool 子模块（或 `$GR_CUSTOM_TOOL`）加入 `sys.path`，供 `gr4_editor` 使用 |
| `fw.py` | RTOS 地址辅助工具、交叉引用（MOVW/MOVT、BL、字面量）、反汇编 |
| `emu.py` | Unicorn 仿真框架（内存分配 / assert / 日志 / SVC 桩函数） |
| `run_tuning.py` | 针对指定内部色调槽位运行 `ImageTuningStill::Make`，返回 R2Y 参数块 |
| `diffmodes.py`、`sens.py` | 比较各模式 / 各图像参数下的 R2Y 输出差异 |
| `cube_fit.py` | 把 .cube LUT 拟合为风格矩阵 + 交叉冲洗曲线（需在装有 colour-science/scipy 的 venv 中运行，例如 spektrafilm 的环境） |
| `make_film.py` | 把 cube_fit 结果写入交叉冲洗模式（独立记录 + 矩阵 + 9 条曲线） |
| `verify_film.py` | 对 make_film 输出做离线检查，并与原厂固件比较仿真的 R2Y 差异 |
| `make_films.py` | 用四种胶片模式替换交叉冲洗 / 鲜艳 / 复古 / HDR 色调（记录、曲线、选择器代码补丁）+ 图标 + 名称（FINDINGS §14） |
| `make_icons.py`、`make_names.py` | 重绘 ICONBIN 中的模式图标 / 在全部 21 种界面语言中重命名模式（供 make_films 调用） |
| `verify_films.py` | 对 make_films 输出做离线检查（仿真静态拍摄 + 实时取景、名称、图标） |
| `make_ma_probe.py`、`make_ma_probe2.py`、`verify_ma_probe*.py`、`make_hue_chart.py` | MultiAxial 探测固件（FINDINGS §15、§16）及其色卡 |
| `raw_nr.py` | RAW（PPU Bayer）降噪补丁：关闭（`make_films.py --raw-nr-off`，§21）、仅在 ISO ≥ 6400 时开启（`--raw-nr-from-6400`，§21b）/ 仅在指定 ISO 以上开启（`--raw-nr-above 8000`，§21c） |
| `raw_noise.py` | 测量 DNG 中的噪声相关性，以检测 RAW 降噪（FINDINGS §21） |
| `cca1.py`、`cca1_fit.py`、`verify_cca1.py` | 各胶片的 3x3 CCA1 暖色修正：拟合、补丁（`make_films.py --cca1`）、仿真检查（FINDINGS §22g；v10 起由 film_cave.py 取代） |
| `joint_fit.py` | 联合重拟合风格矩阵 + 胶片曲线 + 后置 3x3 矩阵（胶片 v9，FINDINGS §22i） |
| `make_films10.py`、`film_cave.py`、`armasm.py`、`verify_films10.py` | 胶片 v10：五种胶片（漂白效果 -> Vision3 250D，曲线以节点形式存储），通过 RGB->YCbCr 矩阵实现伽马后 3x3 矩阵，仿真检查（FINDINGS §22l；需要 Homebrew llvm 提供的 llvm-mc） |
| `lab_fit.py` | 以感知色差（dE2000）重新拟合：风格矩阵 + 后置矩阵 + 曲线修正（胶片 v11，FINDINGS §22m） |
| `make_cca1_probe.py` | 临时固件：v7 + CCA1 红蓝互换（证明 CCA1 处于生效状态） |
| `eval_warm.py` | 胶片拟合在暖色（黄/橙）与整体上的误差（胶片 v3，FINDINGS §19） |
| `gr3patch.py` | 概念验证构建器：修补风格矩阵并重新打包容器（复用原厂数据帧） |

已在一台 GR III（固件 2.10）上实机测试：胶片 v2–v10 及 RAW 降噪版本（FINDINGS §14–§22m）。胶片 v11 尚未实机测试。
