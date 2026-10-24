#!/usr/bin/env python3
"""GR III (fwdc239b 2.10) -> GR IIIx (fwdc243b 1.70) 地址自动重定位器。

原理：GR IIIx 1.70 与 GR III 2.10 的 RTOS 代码大量同源但整体重排。
引擎 patch 的每个地址在 GR III 2.10 里有已知原始字节（preimage）。
对每个地址取「patch 点前 N 字节 + 点后 M 字节」的指纹（跳过 patch 点本身），
在 GR IIIx 1.70 的 RTOS 中搜索唯一命中 → 新地址。

用法：
  python relocate_gr3x.py                # 输出映射表 JSON 到 work/gr3x_addr_map.json
仅做只读分析，不改任何固件。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import codec_path  # noqa: F401
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows

BASE = 0x53000000
FW_GR3 = os.environ.get('FW_GR3', os.path.join(os.path.dirname(HERE), 'fwdc239b.bin'))
FW_GR3X = os.environ.get('FW_GR3X', '/Users/macmini/Downloads/fwdc243b.bin')

# 引擎引用的全部地址（name -> GR III 2.10 地址）。与 make_slots15/16、film_cave、gr3patch 一致。
ADDRS = {
    # make_slots15 顶部
    'ICON_G1_FAIL': 0x53209FC4,
    'ICON_G2_FAIL': 0x53209FF8,
    'ICON_DRAW_BOUND': 0x5320A7CC,
    'ICON_DRAW_AT': 0x5320A80C,
    'ICON_DRAW_RET': 0x5320A814,
    'ICON_DRAW_ENTER': 0x5320A7AC,
    'RANDOM': 0x536EF618,
    'PRESET': 0x536EF6DC,
    'AREA_A': 0x536EF61C,
    'AREA_A_END': 0x536EF6DC,
    'AREA_B': 0x536EF6FC,
    'AREA_B_END': 0x536EF998,
    'AREA_C': 0x536EF088,
    'AREA_C_END': 0x536EF140,
    'AREA_D': 0x536EF99C,
    'AREA_D_END': 0x536EF9B8,
    'MOVIE_TABLES_0': 0x53B59234,
    'MOVIE_TABLES_1': 0x53B591C8,
    'MOVIE_TABLES_2': 0x53B5936C,
    'MDISP_DEFAULT': 0x5326C3F4,
    'MDISP_RET': 0x5326C3E0,
    'MDISP_FAIL': 0x5326C454,
    'MDISP_CASE': 0x5326C384,
    'COUNT_AT': 0x532C2ACC,
    'IDX2TONE_0': 0x532C2D60,
    'IDX2TONE_0b': 0x532C2D64,
    'IDX2TONE_TBL0': 0x53B59224,
    'IDX2TONE_1': 0x532C2D80,
    'IDX2TONE_1b': 0x532C2D84,
    'IDX2TONE_TBL1': 0x53B58FCC,
    'IDX2TONE_2': 0x532C2D00,
    'IDX2TONE_2b': 0x532C2D04,
    'IDX2TONE_TBL2': 0x53B5919C,
    'TONE2IDX_0': 0x532C2F58,
    'TONE2IDX_0b': 0x532C2F60,
    'TONE2IDX_1': 0x532C2FF0,
    'TONE2IDX_1b': 0x532C2FF8,
    'TONE2IDX_2': 0x532C3074,
    'TONE2IDX_2b': 0x532C307C,
    'TONE2IDX_CMP_0': 0x532C2F74,
    'TONE2IDX_CMP_1': 0x532C300C,
    'TONE2IDX_CMP_2': 0x532C3090,
    'NAME_FN': 0x532922B4,
    'ICON_FN': 0x532935DC,
    'DISP_DEFAULT': 0x5326C240,
    'DISP_RET': 0x5326C22C,
    'DISP_FAIL': 0x5326C2A0,
    'DSTR_DEFAULT': 0x532A9874,
    'DSTR_RET': 0x532A98E0,
    'DSTR_FAIL': 0x532A9958,
    'DICON_DEFAULT': 0x532A99A0,
    'DICON_RET': 0x532A9A0C,
    'DICON_FAIL': 0x532A9A84,
    'STR1_BOUND': 0x533966D4,
    'STR1_LOAD': 0x533966FC,
    'STR2_BOUND': 0x533970EC,
    'STR2_LOAD': 0x53397108,
    'PROXY_0': 0x532BD784,
    'PROXY_1': 0x532BDCD8,
    'PROXY_2': 0x532BE22C,
    'PROXY_3': 0x532BE8A0,
    'PROXY_4': 0x532BEF14,
    'PROXY_5': 0x532BF588,
    'PROXY_6': 0x532BFBFC,
    'PROXY_7': 0x532C0DA8,
    'PROXY_8': 0x532C141C,
    'PROXY_9': 0x532C34E8,
    'PROXY_10': 0x532C3B54,
    'PROXY_11': 0x532C41C0,
    'PROXY_12': 0x532C494C,
    'PROXY_13': 0x532C50D8,
    'PROXY_14': 0x532C5864,
    'PROXY_15': 0x532C5FF0,
    'PROXY_16': 0x532C8BD4,
    'PROXY_17': 0x532C9360,
    'SLOT_AT': 0x536DC280,
    'PARAM_AT': 0x536DB7FC,
    'PARAM_PT': 0x536DB7DC,
    'FILL_LDR': 0x536DD450,
    'FILL_AT': 0x536DD454,
    'FILL_CHAIN': 0x536DD4B8,
    'NO_CURVES': 0x536DD458,
    'FILL_TAIL2': 0x536DD464,
    'FILL_SETS_END': 0x536DD510,
    'CSP_CALL': 0x536E4774,
    'CSP_CALC': 0x536E4720,
    'CSP_MAKE': 0x536E4760,
    'GET_CALL': 0x536E87C4,
    'GETTER': 0x536EEDF0,
    'GETTER_COMPOSITE': 0x536E8668,
    'GETSTILL_DISP': 0x532A998C,
    'STILL_PROXY': 0x532750FC,
    'STILL_CASE': 0x5326C1D0,
    'DEFAULT_CASE': 0x5326C384,
    'YCC_SETS_NOTE': 0x536DC2BC,
    # make_slots16
    'MA_TABLE': 0x55018CF0,
    'MA_MAKE': 0x536E4470,
    'ZERO_TABLE': 0x53DC2BF8,
    'MA_TABLE_ALT': 0x55019848,
    'RD_CONV': 0x53288D5C,
    'RD_TONE': 0x53289058,
    'RD_TONE_DEF': 0x53289070,
    'RD_KIND': 0x5318DEA0,
    'SH_KIND': 0x531ACB1C,
    'SH_KIND_CALL': 0x531ACB00,
    'EXIF_WRITER': 0x535C7814,
    'EXIF_CTOR': 0x53599DF8,
    'EXIF_PAIRS': 0x53D2B6F4,
    'EXIF_READ': 0x535BF7D0,
    'EXIF_READ_TAB': 0x53D2D920,
    'RD_COUNT': 0x53283C08,
    'RD_OPT_ENUMS': 0x53B5A988,
    'RD_OPT_COUNT': 0x53283358,
    'RD_OPT_MAX': 0x532833BC,
    'RD_OPT_SLOTS': 0x53B5ACB4,
    'RD_OPT_SLOT_FN': 0x532834D0,
    'RD_OPT_ENUM_FN': 0x532834F0,
    'RD_OPT_SLOT_W0': 0x532834D8,
    'RD_OPT_SLOT_W1': 0x532834F4,
    'RD_OPT_SLOT_W2': 0x532835C8,
    'RD_OPT_SLOT_W3': 0x532835DC,
    'RD_OPT_SLOT_W4': 0x532834DC,
    'RD_OPT_SLOT_W5': 0x53283510,
    'RD_OPT_SLOT_W6': 0x53283564,
    'RD_OPT_ENUM_W0': 0x532835CC,
    'RD_OPT_ENUM_W1': 0x532835E4,
    'RD_CONTROLLER': 0x53190108,
    # film_cave / gr3patch
    'STOCK_SET': 0x53DC2BA0,
    'STOCK_SET_READ': 0x53DC2BB8,
    'ZERO_SRC': 0x53D36400,
    'CURVE_LIB': 0x55037604,
    'RECORDS': 0x55018D94,
}


def rtos_of(path):
    d = open(path, 'rb').read()
    i = inspect_container(d)
    dec, _ = decode_payload(d[128:i['payload_end']], i['decoded_size'])
    rt = [r for r in section_rows(dec) if r['name'] == 'RTOS'][0]
    return dec[rt['start']:rt['end']]


def find_all(hay, needle):
    out, start = [], 0
    while True:
        idx = hay.find(needle, start)
        if idx < 0:
            return out
        out.append(idx)
        start = idx + 1


def locate(a, b, addr, pre_n=24, post_n=24):
    """返回 (offsets_in_b, pre_hits, post_hits)。指纹 = 点前 pre_n + 点后 post_n（跳过点本身 4B）。"""
    off = addr - BASE
    if off < pre_n or off + 4 + post_n > len(a):
        return [], 0, 0
    pre = a[off - pre_n:off]
    post = a[off + 4:off + 4 + post_n]
    pre_hits = find_all(b, pre)
    post_hits = set(find_all(b, post))
    cands = [p for p in pre_hits if (p + 4 + pre_n) in post_hits]
    return cands, len(pre_hits), len(post_hits)


def main():
    a = rtos_of(FW_GR3)
    b = rtos_of(FW_GR3X)
    print(f'GR III RTOS {len(a)} B, GR IIIx RTOS {len(b)} B')
    mapping, manual = {}, []
    for name in sorted(ADDRS):
        addr = ADDRS[name]
        got = None
        for pn, sn in ((24, 24), (48, 48), (96, 96), (160, 160)):
            cands, _, _ = locate(a, b, addr, pn, sn)
            if len(cands) == 1:
                got = cands[0]
                break
        if got is None:
            cands, ph, sh = locate(a, b, addr, 24, 24)
            manual.append((name, addr, len(cands), ph, sh))
            print(f'MANUAL {name:18s} 0x{addr:08X} cands={len(cands)} preHits={ph} postHits={sh}')
        else:
            new = BASE + got
            mapping[name] = {'old': addr, 'new': new, 'delta': got - (addr - BASE)}
            print(f'OK     {name:18s} 0x{addr:08X} -> 0x{new:08X}  delta={got - (addr - BASE):+#x}')

    out = os.path.join(HERE, 'work', 'gr3x_addr_map.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(mapping, open(out, 'w'), indent=1)
    print(f'\n自动定位 {len(mapping)}/{len(ADDRS)}，映射表 -> {out}')
    if manual:
        print('待手工分析:', ', '.join(m[0] for m in manual))


if __name__ == '__main__':
    main()
