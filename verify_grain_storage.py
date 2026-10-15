"""Verify the native-grain value storage (make_grain_native.patch_storage).

SetParticle 0x532C1780 / GetDefaultValueParticle 0x532C9744: films (25+) must take the Monotone
path (read/write SI+0x45e, sync SI+0x795) instead of the no-op / assert default.

We emulate both functions with the necessary sub-calls stubbed, and check that for a film tone the
grain value actually lands in SI+0x45e (SetParticle) and is read back (GetDefaultValueParticle),
while stock tones keep the original behaviour.

Usage: python verify_grain_storage.py stock.bin patched.bin [n_films]
"""
import sys, struct
import codec_path  # noqa: F401
from emu import Emu
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload, section_rows
from unicorn import arm_const as A

SETP = 0x532C1780
GETD = 0x532C9744
# grain has THREE parameter types (type = 0x532bd6d4 return), each with its own SI field + write fn:
#   type 0 -> 0x5325dc3c (SI+0x29a)   type 1 -> 0x532601cc (SI+0x37c)   type 2 -> 0x5326276c (SI+0x45e)
MONO_WRITE = {0: 0x5325DC3C, 1: 0x532601CC, 2: 0x5326276C}
FIELD_OFF = {0: 0x29A, 1: 0x37C, 2: 0x45E}
SETTER = 0x5354C570        # property 0xC3 setter (writes SI+0x795)
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


def emu_setparticle(rtos, tone, value, typ):
    """Emulate SetParticle for one grain parameter type and return the field-write + setter result.

    SetParticle(r0=obj, r1=value).  Internals: r4=obj, r6=value; bl 0x53549ee8 -> tone (->r5);
    bl 0x532bd6d4(obj) -> typ (->r7); [obj+0x1b] must be 0.  The film branch tail-calls the per-type
    Monotone write fn (r0=holder, r1=value).  We stub the helpers and record the target field write
    + setter call.
    """
    e = Emu(rtos)
    obj = e.alloc(0x80)
    si = e.alloc(0x800)
    e.w8(obj + 0x1b, 0)
    e.w32(obj + 4, si)
    for off in FIELD_OFF.values():
        e.w8(si + off, 0)

    holder = e.alloc(0x20)
    e.w32(holder + 4, si)

    writes = []
    setter_calls = []
    setter_values = []

    def stub_53525d5c(em): return obj
    def stub_53549ee8(em): return tone
    def stub_532bd6d4(em): return typ
    def stub_5320b31c(em): return holder
    e.extra_stubs[0x53525d5c] = stub_53525d5c
    e.extra_stubs[0x53549ee8] = stub_53549ee8
    e.extra_stubs[0x532bd6d4] = stub_532bd6d4
    e.extra_stubs[0x5320ad88] = 0
    e.extra_stubs[0x5320b31c] = stub_5320b31c
    def stub_setter(em):
        v = em.u.reg_read(A.UC_ARM_REG_R1)
        setter_values.append(v); setter_calls.append(True)
        em.w8(si + 0x795, v)
        return 0
    e.extra_stubs[0x5354C570] = stub_setter

    from unicorn import UC_HOOK_MEM_WRITE
    field = si + FIELD_OFF[typ]
    def _w(u, access, addr, size, value, _):
        if addr == field:
            writes.append(value)
    e.u.hook_add(UC_HOOK_MEM_WRITE, _w)

    e.call(SETP, obj, value)
    return {
        'field': e.r32(field) & 0xFF,
        'grain_795': e.r32(si + 0x795) & 0xFF,
        'wrote': len(writes) > 0,
        'setter_called': len(setter_calls) > 0,
        'setter_value': setter_values[0] if setter_values else None,
    }


S = rtos_of(sys.argv[1])
P = rtos_of(sys.argv[2])

# films: patched must write ALL THREE fields + sync SI+0x795; stock must stay no-op
films_ok = True
for typ in (0, 1, 2):
    for k in range(n):
        tone = 25 + k
        s = emu_setparticle(S, tone, 2, typ)
        p = emu_setparticle(P, tone, 2, typ)
        if not (p['wrote'] and p['setter_called'] and p['field'] == 2 and p['grain_795'] == 2):
            films_ok = False
            check(False, f'film tone {tone} type {typ}: patched={p} (want wrote/setter_called, field=795=2)')
        if s['wrote'] or s['setter_called']:
            films_ok = False
            check(False, f'stock film tone {tone} type {typ} should be no-op but wrote={s["wrote"]} setter_called={s["setter_called"]}')
check(films_ok, f'films 25..{25+n-1} all 3 types: patched writes field + syncs SI+0x795, stock stays no-op')

# stock tones 13/14/15 (Monotone etc.) must be UNCHANGED by the patch
for typ in (0, 1, 2):
    for tone in (13, 14, 15):
        s = emu_setparticle(S, tone, 2, typ)
        p = emu_setparticle(P, tone, 2, typ)
        check(s == p, f'stock tone {tone} type {typ} SetParticle unchanged by patch (stock={s}, patched={p})')

print()
print('ALL OK' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
