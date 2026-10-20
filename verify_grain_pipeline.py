"""Verify the native-grain pipeline pass-through (make_grain_native.patch_pipeline).

Standard case 0x536DBAA4 copies SI+0x793(Shading)->ctx+0x1F4, SI+0x794(Clarity)->ctx+0x1F6 and
writes 0 to ctx+0x1F8 (Grain).  The fix makes ctx+0x1F8 = SI+0x795.

The pass-through 0x536DB7DC: r0 = ctx (output block), r1 = obj with +0x2ac (set index) and
+0x2d0 (SI base).  We emulate it and read ctx+0x1F8.

Usage: python verify_grain_pipeline.py stock.bin patched.bin
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows

PT = 0x536DB7DC

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


def _run(rtos, tone, grain):
    """Shared emulation: return (ctx+0x1F8, SI+0x795 after the epilogue write-back)."""
    e = Emu(rtos)
    ctx = e.alloc(0x300)
    obj = e.alloc(0x40)
    si = e.alloc(0x800)
    # obj fields read by 0x536DB7DC: +0x2ac (byte), +0x2d0 (SI pointer)
    e.w8(obj + 0x2ac, 0)
    e.w32(obj + 0x2d0, si)
    e.w8(si + 0x77c, tone)      # tone
    e.w8(si + 0x77d, 0)         # the block copied into ctx+0x1e0.. (fill with 0)
    e.w8(si + 0x793, 4)         # shading = 4 (neutral)
    e.w8(si + 0x794, 4)         # clarity = 4 (neutral)
    e.w8(si + 0x795, grain)     # grain
    e.call(PT, ctx, obj)
    ctx_1f8 = struct.unpack('<H', e.u.mem_read(ctx + 0x1F8, 2))[0]
    si_795 = e.u.mem_read(si + 0x795, 1)[0]   # value AFTER the epilogue write-back
    return ctx_1f8, si_795


def pt_result(rtos, tone, grain):
    """Emulate the pass-through for (tone, grain) and return ctx+0x1F8 (u16)."""
    return _run(rtos, tone, grain)[0]


def pt_writeback(rtos, tone, grain):
    """Return (ctx+0x1F8, SI+0x795-after-epilogue).  The 2nd is the regression we are fixing:
    before the fix, the epilogue zeroed SI+0x795 (grain reset to OFF right after a shot)."""
    return _run(rtos, tone, grain)


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# Standard (tone 11): its real SI+0x795 is ALWAYS 0 (no setter path — confirmed by the 0 direct
# strb [rX,#0x795] writes and the fact that the 0xC3 setter is only called from the Monotone
# SetParticle branch).  So the only reachable case is grain=0; both must give ctx+0x1F8=0.
check(pt_result(S, 11, 0) == 0 and pt_result(P, 11, 0) == 0,
      f'Standard tone 11 (grain=0, the only reachable state): ctx+0x1F8 == 0 (stock {pt_result(S,11,0)}, fixed {pt_result(P,11,0)})')

# sanity: even with a non-zero grain injected, the film path must carry it (this is the whole point)
check(pt_result(P, 11, 2) == 2, 'Standard case now carries SI+0x795 through (harmless: Standard grain is always 0 in practice)')

# films (tone 25+): stock forces 0; fixed carries SI+0x795 through
films_ok = True
for tone in (25, 26, 27, 28):
    for g in (0, 1, 2, 3):
        s = pt_result(S, tone, g)
        p = pt_result(P, tone, g)
        if s != 0 or p != g:
            films_ok = False
            check(False, f'film tone {tone} grain={g}: stock={s} (want 0), fixed={p} (want {g})')
            break
check(films_ok, 'films tone 25-28: stock forces 0, fixed carries SI+0x795')

# ★ 回写验证（修复的核心）：pipeline 的 epilogue 0x536db9c8 是 `strb r6,[r3,#0x795]`。
#   修复前 stub 用 r2 承载 grain，epilogue 用 r6=0 把 SI+0x795 清成 0 —— 拍完颗粒跳回 OFF。
#   修复后必须原样写回（SI+0x795 == grain）。
wb_ok = True
for tone in (25, 26, 27, 28):
    for g in (1, 2, 3):
        p_ctx, p_si = pt_writeback(P, tone, g)
        if p_ctx != g or p_si != g:
            wb_ok = False
            check(False, f'film tone {tone} grain={g}: fixed ctx={p_ctx} (want {g}), SI+0x795 writeback={p_si} (want {g})')
            break
check(wb_ok, 'films tone 25-28: epilogue writes SI+0x795 back unchanged (grain survives the shot)')

# 对照组：修复前的固件确实会把 SI+0x795 清零（确认 bug 存在，且我们的验证能抓住它）
s_ctx, s_si = pt_writeback(S, 25, 2)
check(s_ctx == 0 and s_si == 0,
      f'stock film tone 25 grain=2: ctx={s_ctx} (want 0), SI+0x795 writeback={s_si} (want 0 — the reset bug)')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
