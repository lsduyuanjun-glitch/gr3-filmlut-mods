"""GR III / GR IIIx 地址映射表 —— 机型分发的唯一权威地址源。

背景（FINDINGS 2026-10-24~25 逆向）：
  - 引擎（make_slots15/16、film_cave、gr3patch、make_grain_native）里的地址都是
    GR III 2.10 (fwdc239b.bin) 的硬编码地址，基址 BASE = 0x53000000。
  - GR IIIx 1.70 (fwdc243b.bin) 与 GR III 2.10 的 RTOS 同源但「分段重排」：
    不同代码段有各自的固定偏移（delta），已观察到这些稳定段：
        -0x40    : pipeline/film_cave 核心区（0x536Dxxxx / 0x536Exxxx 一带）
        +0xc0    : 图标 getter/draw、菜单 case（0x5320xxxx / 0x5326xxxx 一带）
        +0xd8    : 字符串 getter、代理函数头部（0x532Bxxxx / 0x5339xxxx 一带）
        +0xdc    : NAME_FN / ICON_FN（0x5329xxxx 一带）
        -0x6f0   : 只读数据表（0x53B5xxxx 一带）
        -0x6c0   : 只读数据（0x53D3xxxx 一带）
        +0x120   : 零表（0x53DCxxxx 一带）
        -0x638   : EXIF pairs（0x53D2xxxx 一带）
  - 本表把「符号名 → GR III 地址」和「已定位的 GR IIIx 地址」集中管理。
    relocate_gr3x.py 负责逆向并更新 gr3x_addr_map.json；本表读它做运行时分发。

职责：
  - 提供 gr3x_of(addr) 把任意 GR III 2.10 地址映射到 GR IIIx 1.70 地址。
  - 未定位的地址返回 None（调用方据此报错，绝不静默用错地址）。

红线：未定位的地址绝不能用「猜的 delta」填——每个 delta 段边界必须靠字节指纹
唯一命中确认（relocate_gr3x.py 已做 47 个）。其余待手工逆向补全后，本表自动生效。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# GR IIIx 1.70 官方固件 SHA（与 webtool/models.py 一致）
GR3X_1_70_SHA = 'aa8e3ae1349d94e83be381c20530e41d5e57b75c27ef24ba81c7b017d6c11592'
# GR III 2.10 官方固件 SHA
GR3_2_10_SHA = 'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4'

_MAP_PATH = os.path.join(HERE, 'work', 'gr3x_addr_map.json')

# 符号名 → GR III 2.10 地址（与 relocate_gr3x.py ADDRS 一致，权威源）
GR3_ADDRS = {
    'ICON_G1_FAIL': 0x53209FC4, 'ICON_G2_FAIL': 0x53209FF8,
    'ICON_DRAW_BOUND': 0x5320A7CC, 'ICON_DRAW_AT': 0x5320A80C, 'ICON_DRAW_RET': 0x5320A814,
    'ICON_DRAW_ENTER': 0x5320A7AC,
    'RANDOM': 0x536EF618, 'PRESET': 0x536EF6DC,
    'AREA_A': 0x536EF61C, 'AREA_A_END': 0x536EF6DC,
    'AREA_B': 0x536EF6FC, 'AREA_B_END': 0x536EF998,
    'AREA_C': 0x536EF088, 'AREA_C_END': 0x536EF140,
    'AREA_D': 0x536EF99C, 'AREA_D_END': 0x536EF9B8,
    'MOVIE_TABLES_0': 0x53B59234, 'MOVIE_TABLES_1': 0x53B591C8, 'MOVIE_TABLES_2': 0x53B5936C,
    'MDISP_DEFAULT': 0x5326C3F4, 'MDISP_RET': 0x5326C3E0, 'MDISP_FAIL': 0x5326C454, 'MDISP_CASE': 0x5326C384,
    'COUNT_AT': 0x532C2ACC,
    'IDX2TONE_0': 0x532C2D60, 'IDX2TONE_0b': 0x532C2D64, 'IDX2TONE_TBL0': 0x53B59224,
    'IDX2TONE_1': 0x532C2D80, 'IDX2TONE_1b': 0x532C2D84, 'IDX2TONE_TBL1': 0x53B58FCC,
    'IDX2TONE_2': 0x532C2D00, 'IDX2TONE_2b': 0x532C2D04, 'IDX2TONE_TBL2': 0x53B5919C,
    'TONE2IDX_0': 0x532C2F58, 'TONE2IDX_0b': 0x532C2F60,
    'TONE2IDX_1': 0x532C2FF0, 'TONE2IDX_1b': 0x532C2FF8,
    'TONE2IDX_2': 0x532C3074, 'TONE2IDX_2b': 0x532C307C,
    'TONE2IDX_CMP_0': 0x532C2F74, 'TONE2IDX_CMP_1': 0x532C300C, 'TONE2IDX_CMP_2': 0x532C3090,
    'NAME_FN': 0x532922B4, 'ICON_FN': 0x532935DC,
    'DISP_DEFAULT': 0x5326C240, 'DISP_RET': 0x5326C22C, 'DISP_FAIL': 0x5326C2A0,
    'DSTR_DEFAULT': 0x532A9874, 'DSTR_RET': 0x532A98E0, 'DSTR_FAIL': 0x532A9958,
    'DICON_DEFAULT': 0x532A99A0, 'DICON_RET': 0x532A9A0C, 'DICON_FAIL': 0x532A9A84,
    'STR1_BOUND': 0x533966D4, 'STR1_LOAD': 0x533966FC,
    'STR2_BOUND': 0x533970EC, 'STR2_LOAD': 0x53397108,
    'PROXY_0': 0x532BD784, 'PROXY_1': 0x532BDCD8, 'PROXY_2': 0x532BE22C, 'PROXY_3': 0x532BE8A0,
    'PROXY_4': 0x532BEF14, 'PROXY_5': 0x532BF588, 'PROXY_6': 0x532BFBFC, 'PROXY_7': 0x532C0DA8,
    'PROXY_8': 0x532C141C, 'PROXY_9': 0x532C34E8, 'PROXY_10': 0x532C3B54, 'PROXY_11': 0x532C41C0,
    'PROXY_12': 0x532C494C, 'PROXY_13': 0x532C50D8, 'PROXY_14': 0x532C5864, 'PROXY_15': 0x532C5FF0,
    'PROXY_16': 0x532C8BD4, 'PROXY_17': 0x532C9360,
    'SLOT_AT': 0x536DC280, 'PARAM_AT': 0x536DB7FC, 'PARAM_PT': 0x536DB7DC,
    'FILL_LDR': 0x536DD450, 'FILL_AT': 0x536DD454, 'FILL_CHAIN': 0x536DD4B8,
    'NO_CURVES': 0x536DD458, 'FILL_TAIL2': 0x536DD464, 'FILL_SETS_END': 0x536DD510,
    'CSP_CALL': 0x536E4774, 'CSP_CALC': 0x536E4720, 'CSP_MAKE': 0x536E4760,
    'GET_CALL': 0x536E87C4, 'GETTER': 0x536EEDF0, 'GETTER_COMPOSITE': 0x536E8668,
    'GETSTILL_DISP': 0x532A998C, 'STILL_PROXY': 0x532750FC, 'STILL_CASE': 0x5326C1D0,
    'DEFAULT_CASE': 0x5326C384, 'YCC_SETS_NOTE': 0x536DC2BC,
    'MA_TABLE': 0x55018CF0, 'MA_MAKE': 0x536E4470, 'ZERO_TABLE': 0x53DC2BF8,
    'MA_TABLE_ALT': 0x55019848,
    'RD_CONV': 0x53288D5C, 'RD_TONE': 0x53289058, 'RD_TONE_DEF': 0x53289070,
    'RD_KIND': 0x5318DEA0, 'SH_KIND': 0x531ACB1C, 'SH_KIND_CALL': 0x531ACB00,
    'EXIF_WRITER': 0x535C7814, 'EXIF_CTOR': 0x53599DF8, 'EXIF_PAIRS': 0x53D2B6F4,
    'EXIF_READ': 0x535BF7D0, 'EXIF_READ_TAB': 0x53D2D920,
    'RD_COUNT': 0x53283C08, 'RD_OPT_ENUMS': 0x53B5A988, 'RD_OPT_COUNT': 0x53283358,
    'RD_OPT_MAX': 0x532833BC, 'RD_OPT_SLOTS': 0x53B5ACB4,
    'RD_OPT_SLOT_FN': 0x532834D0, 'RD_OPT_ENUM_FN': 0x532834F0,
    'RD_OPT_SLOT_W0': 0x532834D8, 'RD_OPT_SLOT_W1': 0x532834F4, 'RD_OPT_SLOT_W2': 0x532835C8,
    'RD_OPT_SLOT_W3': 0x532835DC, 'RD_OPT_SLOT_W4': 0x532834DC, 'RD_OPT_SLOT_W5': 0x53283510,
    'RD_OPT_SLOT_W6': 0x53283564, 'RD_OPT_ENUM_W0': 0x532835CC, 'RD_OPT_ENUM_W1': 0x532835E4,
    'RD_CONTROLLER': 0x53190108,
    'STOCK_SET': 0x53DC2BA0, 'STOCK_SET_READ': 0x53DC2BB8, 'ZERO_SRC': 0x53D36400,
    'CURVE_LIB': 0x55037604, 'RECORDS': 0x55018D94,
}

# 缓存：gr3x_addr_map.json 里的 {符号名: {old, new, delta}}
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_MAP_PATH) as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def gr3x_of(addr):
    """把 GR III 2.10 地址映射到 GR IIIx 1.70 地址；未定位返回 None。

    通过「地址 → 符号名」反查已定位表。因为 relocate 的输出是 {name: {old,new}}，
    这里按 old 值匹配。
    """
    m = _load()
    for entry in m.values():
        if entry.get('old') == addr:
            return entry.get('new')
    return None


def gr3x_addr(name):
    """按符号名取 GR IIIx 1.70 地址；未定位返回 None。"""
    m = _load()
    e = m.get(name)
    return e.get('new') if e else None


def located_count():
    return len(_load())


def total_count():
    return len(GR3_ADDRS)
