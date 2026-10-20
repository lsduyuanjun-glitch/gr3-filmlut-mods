"""Verify the 'keep grain on tone switch' fix (make_grain_native.setparticle_stub_src).

SetParticle has two callers:
  caller A 0x531b0d28  -> return 0x531b0d2c  (menu: user picks a grain step)  -> MUST write
  caller B 0x532c3490  -> return 0x532c3494  (bulk-apply param block on tone switch) -> MUST skip

We emulate SetParticle with a caller-specified LR (the saved return address lives on the
stack at [sp,#32]) and check whether SI+0x29a/0x795 get written.

Usage: python verify_grain_tone_switch.py stock.bin patched.bin [n_films]
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu, STOP
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows
from unicorn import arm_const as A
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_CODE

SETP = 0x532C1780
SP_NOOP = 0x532C1844
FIELD_OFF = {0: 0x29A, 1: 0x37C, 2: 0x45E}
CALLER_A_LR = 0x531B0D2C   # menu pick
CALLER_B_LR = 0x532C3494   # tone-switch bulk apply
n = int(sys.argv[3]) if len(sys.argv) > 3 else 4

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


def emu_setparticle_lr(rtos, tone, value, typ, caller_lr):
    e = Emu(rtos)
    obj = e.alloc(0x80)
    si = e.alloc(0x800)
    e.w8(obj + 0x1b, 0)
    e.w32(obj + 4, si)
    for off in FIELD_OFF.values():
        e.w8(si + off, 0)
    holder = e.alloc(0x20)
    e.w32(holder + 4, si)

    def stub_53525d5c(em): return obj
    def stub_53549ee8(em): return tone
    def stub_532bd6d4(em): return typ
    def stub_5320b31c(em): return holder
    e.extra_stubs[0x53525d5c] = stub_53525d5c
    e.extra_stubs[0x53549ee8] = stub_53549ee8
    e.extra_stubs[0x532bd6d4] = stub_532bd6d4
    e.extra_stubs[0x5320ad88] = 0
    e.extra_stubs[0x5320b31c] = stub_5320b31c
    e.extra_stubs[0x5354C570] = 0   # setter: not reached for the skip path

    field = si + FIELD_OFF[typ]
    wrote_field = [False]
    wrote_795 = [False]
    def _w(u, access, addr, size, value, _):
        if addr == field:
            wrote_field[0] = True
        if addr == si + 0x795:
            wrote_795[0] = True
    e.u.hook_add(UC_HOOK_MEM_WRITE, _w)

    # stop when the stub reaches SP_NOOP (both write and skip paths branch here)
    def _code(u, at, size, _):
        if at == SP_NOOP:
            u.reg_write(A.UC_ARM_REG_PC, STOP)
    e.u.hook_add(UC_HOOK_CODE, _code)

    # manual setup (mirror Emu.call) but with the caller LR we want
    u = e.u
    for i in range(13):
        u.reg_write(getattr(A, f'UC_ARM_REG_R{i}'), 0)
    u.reg_write(A.UC_ARM_REG_R0, obj)
    u.reg_write(A.UC_ARM_REG_R1, value)
    u.reg_write(A.UC_ARM_REG_SP, 0x5F000000 - 0x100)
    u.reg_write(A.UC_ARM_REG_LR, caller_lr)
    u.reg_write(A.UC_ARM_REG_CPSR, 0x13)
    u.emu_start(SETP, STOP, count=5_000_000)
    return wrote_field[0], wrote_795[0], e.r32(field) & 0xFF, e.r32(si + 0x795) & 0xFF


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# caller A (menu pick) must still WRITE on the film path
a_ok = True
for typ in (0, 1, 2):
    wf, w795, fv, gv = emu_setparticle_lr(P, 25, 2, typ, CALLER_A_LR)
    if not (wf and w795 and fv == 2 and gv == 2):
        a_ok = False
        check(False, f'caller A film tone 25 type {typ}: wrote_field={wf} wrote_795={w795} field={fv} 795={gv} (want all True/2)')
check(a_ok, 'caller A (menu pick): film grain still writes SI field + 0x795')

# caller B (tone switch) must SKIP on the film path -> SI grain untouched (0)
b_ok = True
for typ in (0, 1, 2):
    wf, w795, fv, gv = emu_setparticle_lr(P, 25, 2, typ, CALLER_B_LR)
    if wf or w795 or fv != 0 or gv != 0:
        b_ok = False
        check(False, f'caller B film tone 25 type {typ}: wrote_field={wf} wrote_795={w795} field={fv} 795={gv} (want all False/0)')
check(b_ok, 'caller B (tone switch): film grain is NOT overwritten (keeps user value)')

# stock firmware: caller B also writes nothing for films (it was already a no-op), sanity only
s_wf, s_w795, s_fv, s_gv = emu_setparticle_lr(S, 25, 2, 0, CALLER_B_LR)
check(not s_wf and not s_w795, 'stock caller B film: unchanged (no-op)')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
