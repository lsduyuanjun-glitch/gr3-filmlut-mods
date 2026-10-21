#!/usr/bin/env python3
"""GR3 机型注册表 —— 每个机型 → 官方固件身份 + patch 配置。

模仿 GRMod（GPL-2.0）的「机型矩阵」模式（ricoh.go / factory.ts）：
  - 机型身份靠**官方固件 SHA256** 识别，不靠文件名（与本仓库 paths._fw_sha_ok 同思路）
  - 每个机型有独立的官方固件 SHA + patch 配置
  - UI 选机型 → 加载对应 patch 集

职责边界：
  - 本模块**纯数据 + 查询**，不读文件、不依赖 paths/网络，便于单测与 CLI 复用。
  - 固件「下载/定位」在 paths.find_firmware(model_id) 里做（按本表 SHA 自动识别）。
  - 逆向细节（偏移/签名）逐机型填进 `patch`，先占位、后填充，不做破坏性改动。

当前状态：仅 GR III 已逆向验证（supported=True）；其余三款为骨架占位（supported=False），
在 server 端与 UI 端都会被闸门拦住，绝不会静默产出错误固件。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ModelSpec:
    id: str
    display_name: str                     # 用户可见名
    family: str                           # GR III / GR IIIx / GR III HDF / GR IIIx HDF
    # 官方固件身份（运行时校验 SHA256；本工具不内置固件，避免 Ricoh 版权分发）
    official_firmware_sha256: str = ""    # 已知官方固件 SHA；空 = 尚未逆向
    official_firmware_version: str = ""   # 人类可读版本号，如 "2.10"
    firmware_download: str = ""           # 理光官方下载地址（阶段1 运行时拉取用）
    # patch 配置：每机型的偏移/开关可能不同，先留字段、逐机型逆向填充
    patch: dict[str, Any] = field(default_factory=dict)
    # 该机型是否已真正逆向验证（False = 骨架占位，尚不可用）
    supported: bool = False
    # 逆向备注 / 与 GR III 的差异点
    note: str = ""


# —— 机型矩阵 ——
# GR III 已填满；其余三款为占位骨架，待阶段2 逆向后填 expected_sha + patch。
MODELS: dict[str, ModelSpec] = {
    "gr3": ModelSpec(
        id="gr3",
        display_name="Ricoh GR III",
        family="GR III",
        official_firmware_sha256="d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4",
        official_firmware_version="2.10",
        firmware_download="",
        # v16 管线关键开关（与 build_firmware.build 当前逻辑一致）
        patch={
            "modules": ["make_slots15", "make_slots16", "gr3patch", "make_grain_native"],
            "append_tone_base": 25,   # 胶片作为新增影像控制项，追加在 tone 25+ 槽位
            "multiaxial": True,       # 12 分区色相校正
            "rawdev": True,           # RAW 显影兼容
        },
        supported=True,
        note="已逆向验证：胶片追加 + 颗粒引擎 + 解锁码全家桶均跑通（v1.5.2）。",
    ),
    "gr3x": ModelSpec(
        id="gr3x",
        display_name="Ricoh GR IIIx",
        family="GR IIIx",
        official_firmware_sha256="",  # TODO(阶段2): 逆向后填入 GR IIIx 官方固件 SHA
        official_firmware_version="",
        firmware_download="",
        patch={},                     # TODO(阶段2): 填 GR IIIx 偏移（与 III 共用底层，需实测）
        supported=False,
        note="40mm 等效焦段；与 GR III 底层共用最多，优先逆向。",
    ),
    "gr3hdf": ModelSpec(
        id="gr3hdf",
        display_name="Ricoh GR III HDF",
        family="GR III HDF",
        official_firmware_sha256="",  # TODO(阶段2)
        official_firmware_version="",
        firmware_download="",
        patch={},
        supported=False,
        note="比 GR III 多 HDF 滤镜；先啃 GR IIIx 再跟。",
    ),
    "gr3xhdf": ModelSpec(
        id="gr3xhdf",
        display_name="Ricoh GR IIIx HDF",
        family="GR IIIx HDF",
        official_firmware_sha256="",  # TODO(阶段2)
        official_firmware_version="",
        firmware_download="",
        patch={},
        supported=False,
        note="GR IIIx + HDF 叠加；最后做。",
    ),
}

DEFAULT_MODEL = "gr3"


def get_model(model_id: Optional[str] = None) -> ModelSpec:
    """取机型规格；非法/空 → 回退默认 GR III（保证向后兼容）。"""
    if not model_id:
        return MODELS[DEFAULT_MODEL]
    return MODELS.get(model_id, MODELS[DEFAULT_MODEL])


def is_supported(model_id: Optional[str] = None) -> bool:
    return get_model(model_id).supported


def expected_sha(model_id: Optional[str] = None) -> str:
    """取该机型已知官方固件 SHA；未逆向返回空串（调用方据此报错）。"""
    return get_model(model_id).official_firmware_sha256


def list_models() -> list[tuple[str, str, str, bool]]:
    """供 UI 展示：[(id, display_name, family, supported)]，保持注册表声明顺序。"""
    return [(m.id, m.display_name, m.family, m.supported) for m in MODELS.values()]


def require_supported(model_id: Optional[str] = None) -> ModelSpec:
    """取已支持机型；否则抛 ValueError（server 端把异常转成 400/403 给用户）。"""
    spec = get_model(model_id)
    if not spec.supported:
        raise ValueError(
            f"机型「{spec.display_name}」尚未开放：{spec.note or '待逆向'}"
        )
    return spec
