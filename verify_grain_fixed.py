"""Verify the 'baked-in grain' path (make_grain_native.patch_fixed_grain).

The fixed-grain mode must write a FIXED value into ctx+0x1F8 and SI+0x795 regardless of the
SI grain field (which the tone switch resets to 0).  So even with SI+0x795 == 0 (the post-tone-switch
state), the film must still render grain = fixed_value.

Usage: python verify_grain_fixed.py stock.bin patched.bin fixed_value [n_films]
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows

PT = 0x536DB7DC
_ga = sys.argv[3] if len(sys.argv) > 3 else '2'
n = int(sys.argv[4]) if len(sys.argv) > 4 else 4
if ',' in _ga:
    grains = [int(x) for x in _ga.split(',')]
else:
    grains = [int(_ga)] * n
grains = (grains + [2] * n)[:n]

ok = True
def check(cond, msg):
    global ok
    ok &= bool(cond)
    print(('OK   ' if cond else 'FAIL ') + msg)


def rtos_of(path):
    d = open(path, 'rb').read()
    i = inspect_container(d)
    dec, _ = decode_payload(d[128:i['payload_end']], i['decoded_size'])
    rows = {r['name']: r for r in section_rows(dec)}
    return bytes(dec[rows['RTOS']['start'] + 16:rows['RTOS']['end']])


def pt_fixed(rtos, tone, si795):
    """Emulate PT for (tone, si795) and return (ctx+0x1F8, SI+0x795 after epilogue)."""
    e = Emu(rtos)
    ctx = e.alloc(0x300)
    obj = e.alloc(0x40)
    si = e.alloc(0x800)
    e.w8(obj + 0x2ac, 0)
    e.w32(obj + 0x2d0, si)
    e.w8(si + 0x77c, tone)
    e.w8(si + 0x77d, 0)
    e.w8(si + 0x793, 4)
    e.w8(si + 0x794, 4)
    e.w8(si + 0x795, si795)     # simulate the post-tone-switch state (0)
    e.call(PT, ctx, obj)
    ctx_1f8 = struct.unpack('<H', e.u.mem_read(ctx + 0x1F8, 2))[0]
    si_795 = e.u.mem_read(si + 0x795, 1)[0]
    return ctx_1f8, si_795


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# 核心：换滤镜后 SI+0x795 被清成 0，写死模式下胶片仍要出各自槽位的固定颗粒
for i, tone in enumerate(range(25, 25 + n)):
    g = grains[i]
    c, s = pt_fixed(P, tone, 0)   # si795 = 0 (reset state)
    if c != g or s != g:
        check(False, f'film tone {tone} (SI+0x795=0): ctx={c} (want {g}), SI+0x795 writeback={s} (want {g})')
check(True, f'films tone 25..{24 + n} with SI+0x795=0: ctx+0x1F8 = SI+0x795 writeback = {grains} (per-slot grain baked in, survives tone switch)')

# 对照：stock 固件胶片在 si795=0 时 ctx=0（无颗粒）
sc, ss = pt_fixed(S, 25, 0)
check(sc == 0 and ss == 0, f'stock film tone 25 si795=0: ctx={sc} si795={ss} (want 0 — no grain)')

# Standard（tone 11）不能误伤：写死模式对 Standard 也应保持 0（Standard 不走 film）
for tone in (11, 13):
    c, s = pt_fixed(P, tone, 0)
    # Standard(tone11) 分支未 patch；Monotone(tone13) 走自己的分支。两者不应被固定值污染。
    check(c == 0, f'non-film tone {tone}: ctx+0x1F8 = {c} (want 0, unaffected by fixed-grain patch)')

# gate：写死模式下胶片必须固定启用（即使 shading/clarity/grain 全是默认值）
def gate_result(rtos, tone, shading=4, clarity=4, grain=0):
    e = Emu(rtos)
    plan = e.alloc(0x40)
    si = e.alloc(0x800)
    e.w8(si + 0x77C, tone)
    e.w8(si + 0x793, shading)
    e.w8(si + 0x794, clarity)
    e.w8(si + 0x795, grain)
    e.call(0x535131C0, plan, si)
    return e.u.mem_read(plan + 0x24, 1)[0]

g_ok = True
for tone in range(25, 25 + n):
    if gate_result(P, tone, 4, 4, 0) != 1:   # 默认参数下也必须启用
        g_ok = False
        check(False, f'gate film tone {tone} defaults: not enabled (want 1)')
check(g_ok, 'gate: films always enable the stage (even with default params) — grain baked in')
check(gate_result(P, 11, 4, 4, 0) == 0, 'gate: Standard tone 11 unaffected (0)')
check(gate_result(S, 25, 4, 4, 0) == 0, 'gate: stock film tone 25 defaults = 0 (no grain)')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
