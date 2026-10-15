#!/usr/bin/env python3
"""GR III 魔改固件「刷机前完整性自检 + 回刷源校验」脚本。

一键完成三层安全校验，任何一层不过就拒绝刷机，把变砖风险降到最低：

  L1  容器/解码校验和（sum32 == 0）—— 相机会拒绝校验和不对的固件，这是变砖第一防线
  L2  官方回刷源 fwdc239b.bin 的 SHA256 —— 确保回刷源是原厂未篡改的固件
  L3  完整 Unicorn 仿真验证（verify_v3.py）—— 逐槽位验证曲线/矩阵，且确认未改动的
      模式（Monotone/Positive/Bleach/Negative）与 stock 字节级一致

用法：
  python3 safety_check.py <官方固件.bin> <魔改固件.bin>

退出码：0 = 全部通过（可安全刷机）；非 0 = 有 FAIL，禁止刷机。
"""
import sys, os, subprocess, hashlib

EXPECT_SHA = 'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4'
REPO = os.path.dirname(os.path.abspath(__file__))
PY = '/Users/macmini/.workbuddy/binaries/python/envs/default/bin/python3'


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main():
    if len(sys.argv) != 3:
        print('用法: safety_check.py <官方固件.bin> <魔改固件.bin>')
        sys.exit(2)

    stock, patched = sys.argv[1], sys.argv[2]
    ok = True

    # ---- L2: 回刷源 SHA 校验（先做，确保有可靠退路）----
    print('=' * 70)
    print('L2 — 回刷源（官方固件）完整性校验')
    print('=' * 70)
    s = sha256(stock)
    good = s == EXPECT_SHA
    ok &= good
    print(f'  官方固件 SHA256: {s}')
    print(f'  期望值        : {EXPECT_SHA}')
    print(f'  结果          : {"✅ 原厂未篡改，可作回刷源" if good else "❌ 不匹配，禁止刷机/回刷！"}')

    # ---- L1: 容器/解码校验和 ----
    print()
    print('=' * 70)
    print('L1 — 魔改固件校验和（sum32）')
    print('=' * 70)
    r = subprocess.run(
        [PY, '-c', '''
import sys, codec_path
from gr4_editor.codec.container import inspect_container, sum32
from gr4_editor.codec.frames import decode_payload
d = open(sys.argv[1], "rb").read(); i = inspect_container(d)
dec, _ = decode_payload(d[128:i["payload_end"]], i["decoded_size"])
c = sum32(d); dd = sum32(dec)
print(f"container sum32 = {c:#x}  -> {'OK' if c == 0 else 'FAIL'}")
print(f"decoded   sum32 = {dd:#x}  -> {'OK' if dd == 0 else 'FAIL'}")
sys.exit(0 if c == 0 and dd == 0 else 1)
''', patched],
        cwd=REPO, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print('  ❌ 校验和不为 0，相机会拒刷，此固件已损坏！')
        ok &= False
    else:
        print('  ✅ 校验和通过')

    # ---- L3: 完整仿真验证 ----
    print()
    print('=' * 70)
    print('L3 — 完整 Unicorn 仿真验证（5 槽位曲线/矩阵 + 未改动模式）')
    print('=' * 70)
    r = subprocess.run([PY, os.path.join(REPO, 'verify_v3.py'), stock, patched],
                       cwd=REPO, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        ok &= False

    print()
    print('=' * 70)
    print('最终结论:', '✅ 全部通过，可安全刷机' if ok else '❌ 存在 FAIL，禁止刷机！')
    print('=' * 70)
    if ok:
        print('回刷源已确认可靠：把官方固件 fwdc239b.bin 放到 SD 卡根目录，')
        print('关机状态下按住 MENU 键开机 → 选「执行」即可回刷原厂固件。')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
