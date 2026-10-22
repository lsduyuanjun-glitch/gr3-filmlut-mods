# GR3 胶片工具 · 多机型扩展方案（GR III 全家族）

> 目标：把当前**只支持 GR III** 的工具，扩展成覆盖 **GR III / GR IIIx / GR III HDF / GR IIIx HDF** 四款机型。
> 思路来源：模仿你本机已有的开源工具 **GRMod**（GPL-2.0，仓库 `Maxwooow/Ricoh-GRMod`；其 GR IV 编辑器已作为 `third_party/gr-custom-tool/gr4_editor` 引入本仓库作范本）。

---

## 0. 合并架构与刷写边界（设计基线 · 2026-10-22 确认）

> 本节是后续所有扩展的「不可动摇」基线，任何改动都不得违反这两条。

### 0.1 一个软件 = 核心胶片功能 + 多机型框架

把「之前做的胶片工具」与「多机型框架」合并为**同一个软件**：

- **核心（已有，跑在 `model='gr3'` 链路上）**：Duccio 4 款胶片（Portra 400 / Ektar 100 / Vision3 5207 / Vision3 5219）+ 机内原生颗粒引擎 + XMP/.cube 导入自动拟合 + ΔE 看板 + 胶片库 + ed25519 离线付费解锁（5207 永久免费，其余三款付费全家桶）。
- **外壳/调度（已搭骨架）**：`webtool/models.py` 机型注册表 + 网页机型选择器 + 官方固件 SHA256 识别（灵感来自 GRMod）。
- GR III 现为「全功能 + 多机型外壳」合体态，已验证跑通；其余三款（`gr3x` / `gr3hdf` / `gr3xhdf`）`supported=False`，UI 置灰 + server 端 400 拒绝，闸门双重保险。

### 0.2 刷写边界（重要，易误解）

- 工具**只产出**打好补丁的、可刷的固件 `.bin` 文件；**不通过 USB / 线缆直接往相机里写字节**。
- 真正把固件写入相机 = 用户把 `.bin` 拷到 SD 卡根目录 + 触发**理光自带的固件升级模式**（Menu+电源开机 → 执行更新）。
- GRMod 风格只是「工具帮你把 SD 卡备好」，但**写相机那一步仍是理光的升级流程**。
- 准确说法应为：**「生成可刷固件 + 引导 SD 卡安装」**，而非「工具直接刷写相机」。对外文案/手册一律按此表述，避免误导用户以为软件能一键烧录。

### 0.3 跨机型标定提醒（决定后续工作量）

现有胶片拟合数据（`work/films_v16/fits/duccio/`）是 **GR III 2.10 专属标定**（基于该机型传感器/处理管线）。换 GR IIIx / HDF 不是一键复用，须**逐机型逆向 + 重标定**。因此「全功能跨机型」= 逐机型工程，不是一次配置。

---

## 1. 现状盘点（基于本仓库真实代码）

| 位置 | 现状 | 问题 |
|---|---|---|
| `webtool/build_firmware.py` 第 99–102 行 | **硬编码** GR III 2.10 固件 SHA256（`d6a3c9c2…`），不匹配直接报错 | 只认一个机型一个固件 |
| `webtool/paths.py` | `find_firmware()` 靠文件名（`fwdc239b.bin`）+ 单一 `OFFICIAL_FW_SHA` 定位固件 | 多机型时文件名/SHA 冲突 |
| `webtool/server.py` | `_handle_build` 只取模块级 `FW`，不区分机型 | 无法按机型分流固件与 patch |
| `third_party/gr-custom-tool/gr4_editor/` | GRMod 的 GR IV 编辑器副本：`firmware.py`（SHA256 识别）、`versions.py`（版本分配）、`official_catalogs.py`（官方包目录） | 现成「机型注册表」范本，可直接借鉴结构 |

**结论**：你现在的 GR3 工具在 GR III 内核逆向上已经比 GRMod 在 GR IV 上走得更远（颗粒引擎、胶片 LUT、ed25519 解锁都已跑通）。缺的不是逆向能力，而是**「机型矩阵」的工程抽象**——这正是这次要补的。

---

## 2. 对照 GRMod 的架构（要抄的部分）

GRMod 把"多机型"拆成三层 + 一个注册表：

1. **机型注册表（核心）**：`Models` 映射 + `Supported` 归档对象，每个机型记录：官方包地址、**SHA-256**、patch 偏移/签名表。
2. **运行时拉官方固件 + SHA-256 校验**：`shell/` 层从理光官网拉官方包、校验哈希，**不内置任何固件**。
3. **UI 机型选择器**：选完机型自动加载对应 patch 集。
4. **三层代码**：`core/`（平台无关，编解码+patcher）、`ui/`（前端）、`shell/`（桌面壳 + 本地 HTTP API + SD 卡布局）。

我们**不必照搬 Go/TS**，但要复刻 ① 注册表 ② 运行时拉官方固件 ③ 机型选择器 这三件事。

---

## 3. 注册表设计（已落地骨架：`webtool/models.py`）

```python
MODELS = {
  "gr3":    ModelSpec(id, "Ricoh GR III",     family="GR III",
                      official_firmware_sha256="d6a3c9c2…", official_firmware_version="2.10",
                      patch={...}, supported=True),
  "gr3x":   ModelSpec(id, "Ricoh GR IIIx",    family="GR IIIx",
                      official_firmware_sha256="", supported=False),   # TODO 逆向
  "gr3hdf": ModelSpec(id, "Ricoh GR III HDF", family="GR III HDF",
                      official_firmware_sha256="", supported=False),   # TODO 逆向
  "gr3xhdf":ModelSpec(id,"Ricoh GR IIIx HDF", family="GR IIIx HDF",
                      official_firmware_sha256="", supported=False),   # TODO 逆向
}
```

- 识别靠 **SHA256 而非文件名**（与 GRMod、与本仓库现有 `_fw_sha_ok` 思路一致）。
- `supported=False` 的机型在 UI 上置灰、在 server 端直接报错，绝不静默产出错误固件。
- `patch` 字段先留空，逐机型逆向时填入偏移/开关；GR III 的 `patch` 已把现有 v16 管线的关键开关（追加 tone 基址 25、multiaxial、rawdev）固化进去。

---

## 4. 分阶段执行步骤

### 阶段 0 ✅ 已完成（本次）
- 新建 `webtool/models.py` 注册表骨架。
- `build_firmware.build(..., model='gr3')` 改用 `models.expected_sha(model)` 取代硬编码 SHA。
- `paths.find_firmware(model_id)` 按机型 SHA 自动识别固件。
- `server._handle_build` 接收并校验 `model`；`index.html` 加机型选择器（仅 GR III 可选）。
- **默认仍是 `gr3`，现有 v1.5.2 行为零变化。**

### 阶段 1（当前优先 · GR3 先跑通，再去 GR IIIx）✅ 接线已验证
> 用户决策：**先在当前软件把 GR III 跑通、确认默认 GR III 链路可用，再啃 GR IIIx。**

- 验证手段：`webtool/test_gr3_wiring.py`（纯 Python，无需 numpy / 无需真实固件，退出码 0 = 全过）。
  验证项：默认机型=`gr3`；gr3 `supported=True`；**gr3 SHA 与 `gr3patch.EXPECT_SHA` 完全一致（`d6a3c9c288d7…`）**；
  其余三款被闸门拦截（`require_supported` 抛错 / server 返回 400）；`find_firmware('gr3')` 不崩；server 机型分流正确。
- 固件级真实构建：需用户本机提供**官方 GR III 2.10 固件（SHA `d6a3c9c288d7…`、文件名 `fwdc239b.bin`）** + numpy（CI / 本机已有）。
  本环境按合规要求**不内置、不下**官方固件，故只验证「接线 + 闸门」，真机出包由用户本机完成。
- ⚠️ 仓库内 `work/films_v16/fwdc239b.bin`（SHA `d59b43bd…`）**不是**官方固件，且不在构建输入搜索路径上，
  切勿误当成官方固件喂给工具（工具会正确报「固件不匹配」）。

### 阶段 2 · 固件获取合法化（建议，暂缓）
- 把"用户手动放 `.bin`"升级为"**运行时从理光官网拉官方固件 + SHA256 校验**"（照 GRMod 的 `official_catalogs.py` + `ricoh.go`）。
- 好处：① 避免分发 Ricoh 版权固件；② 自动跟随 Ricoh 更新；③ 注册表里的下载地址字段派上用场。
- 风险：理光下载页结构可能变，需加校验失败兜底（回退到手动放 `.bin`）。

### 阶段 3 · 逐机型逆向（核心工作量）
优先级：**GR IIIx → GR III HDF → GR IIIx HDF**（IIIx 与 III 底层共用最多，先啃最像的）。
每款要填进注册表：
1. 官方固件 SHA256（身份识别）；
2. patch 偏移 / 签名差异（各机型固件二进制不同）；
3. 与 GR III 的差异点（HDF 多了 HDF 滤镜、IIIx 是 40mm 等效焦段，菜单/参数可能不同）。

逆向参考先例（公开）：
- `idontknownihil/gr3-film-mods`（Python，GR III 固件 2.10 胶片，32★）——GR III 的工厂菜单关键字/偏移可挖。
- `Mrjie7205/GR-DLC`（明确 "Based on GR Mod" 的 GR 工具包）——社区已在把 GR Mod 方法移植到 GR 系列。

### 阶段 4 · UI / 打包
- `index.html` 机型选择器从"置灰"变为可选，选完自动加载该机型 `patch` 集。
- `gr3_tool.spec` / `gr3_tool.win.spec` 与 CI 矩阵不变（仍是单包多机型，靠运行时选机型，无需每机型一个包）。

### 阶段 5 · 每机型验证
- 每款机型都要真机/固件级验证：胶片追加、颗粒直出、解锁码验签，确认不砖机。
- 严禁用未验证机型产出给用户（注册表 `supported` 闸门守住）。

---

## 5. 风险与红线

- **不内置任何官方固件**（版权 + Ricoh 合规）。阶段 1 的"运行时拉取"是正确方向。
- **私钥 `tools/private_key.pem` 永不入库、永不外泄**；解锁码全家桶（portra400/ektar100/5219）跨机型保持一致。
- **GR IV 编辑器代码（`third_party/gr-custom-tool/gr4_editor`）仅作结构参考**，不要把它混入 GR3 逆向逻辑——两者的固件容器/偏移不同。
- **未验证机型绝不发布**（`supported` 闸门 + server 端报错双重保险）。
- 打包体积：APFS 克隆会让重复产物"看起来很大"但实际不占空间；CI 产物以 zip 为准。

---

## 6. 待逆向清单（填进注册表的 TODO）

| 机型 | 官方固件 SHA256 | patch 偏移 | 与 GR III 差异 | 状态 |
|---|---|---|---|---|
| GR III | `d6a3c9c2…`（已知） | 已知（v16 管线） | — | ✅ 已支持 |
| GR IIIx | 待取 | 待逆 | 40mm 焦段、菜单差异 | ⬜ |
| GR III HDF | 待取 | 待逆 | 多 HDF 滤镜 | ⬜ |
| GR IIIx HDF | 待取 | 待逆 | 上述两者叠加 | ⬜ |

---

## 7. 下一步建议
1. 先把阶段 1（运行时拉官方固件）做了——它会让注册表的 `firmware_download` 字段变得有意义，也让合规更稳。
2. 同时启动阶段 2 的 **GR IIIx** 逆向（最高性价比，与 GR III 共用底层）。
3. HDF 两款等前两者跑通再跟。
