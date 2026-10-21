# GR3 胶片工具 · 多机型扩展方案（GR III 全家族）

> 目标：把当前**只支持 GR III** 的工具，扩展成覆盖 **GR III / GR IIIx / GR III HDF / GR IIIx HDF** 四款机型。
> 思路来源：模仿你本机已有的开源工具 **GRMod**（GPL-2.0，仓库 `Maxwooow/Ricoh-GRMod`；其 GR IV 编辑器已作为 `third_party/gr-custom-tool/gr4_editor` 引入本仓库作范本）。

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

### 阶段 1 · 固件获取合法化（建议优先）
- 把"用户手动放 `.bin`"升级为"**运行时从理光官网拉官方固件 + SHA256 校验**"（照 GRMod 的 `official_catalogs.py` + `ricoh.go`）。
- 好处：① 避免分发 Ricoh 版权固件；② 自动跟随 Ricoh 更新；③ 注册表里的下载地址字段派上用场。
- 风险：理光下载页结构可能变，需加校验失败兜底（回退到手动放 `.bin`）。

### 阶段 2 · 逐机型逆向（核心工作量）
优先级：**GR IIIx → GR III HDF → GR IIIx HDF**（IIIx 与 III 底层共用最多，先啃最像的）。
每款要填进注册表：
1. 官方固件 SHA256（身份识别）；
2. patch 偏移 / 签名差异（各机型固件二进制不同）；
3. 与 GR III 的差异点（HDF 多了 HDF 滤镜、IIIx 是 40mm 等效焦段，菜单/参数可能不同）。

逆向参考先例（公开）：
- `idontknownihil/gr3-film-mods`（Python，GR III 固件 2.10 胶片，32★）——GR III 的工厂菜单关键字/偏移可挖。
- `Mrjie7205/GR-DLC`（明确 "Based on GR Mod" 的 GR 工具包）——社区已在把 GR Mod 方法移植到 GR 系列。

### 阶段 3 · UI / 打包
- `index.html` 机型选择器从"置灰"变为可选，选完自动加载该机型 `patch` 集。
- `gr3_tool.spec` / `gr3_tool.win.spec` 与 CI 矩阵不变（仍是单包多机型，靠运行时选机型，无需每机型一个包）。

### 阶段 4 · 每机型验证
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
