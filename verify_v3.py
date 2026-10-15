"""5-slot verification for the Duccio v3 build (gr3_duccio_v3.bin).

Verifies the patched firmware end-to-end against stock, at three layers:
  1. Container / decoded checksums (sum32 == 0) + byte-diff extent (bricking first line of defence)
  2. Unchanged modes (Standard/Monotone/Positive/Bleach/Negative) produce byte-identical emulated
     R2Y output vs stock
  3. Each replaced slot's composite R/G/B gamma == its fitted curves, and its record look matrix
     == its fitted matrix (5 slots, incl. Standard sharing selector 4 with Vivid)

Usage:
  verify_v3.py <stock.bin> <patched.bin>

The 5-slot fit mapping is read directly from make_films.MODES (standard/vivid/retro/hdr/cross)
and the film JSONs are resolved via the same FILMS table as build_firmware.py.
"""
import sys, json, struct
import codec_path  # noqa: F401  (gr4_editor from the gr-custom-tool submodule)
import numpy as np
from gr4_editor.codec.container import inspect_container, sum32
from gr4_editor.codec.frames import decode_payload, section_rows
from run_tuning import setup, make
from make_films import MODES
from make_film import q13_matrix

# Same film JSON mapping as build_firmware.py (order must match MODES)
FILMS = {
    'standard': 'work/duccio/night5219.json',
    'vivid':    'work/duccio/night5219.json',
    'retro':    'work/duccio/cinema5207.json',
    'hdr':      'work/films/pro400h_crystalarchive.json',
    'cross':    'work/films/portra400_portraendura.json',
}


def decode(path):
    d = open(path, 'rb').read()
    i = inspect_container(d)
    dec, _ = decode_payload(d[128:i['payload_end']], i['decoded_size'])
    return d, dec


def main():
    stock_path, patched_path = sys.argv[1], sys.argv[2]
    fits = [json.load(open(FILMS[m[0]])) for m in MODES]

    (s_raw, s_dec), (p_raw, p_dec) = decode(stock_path), decode(patched_path)

    print('=' * 72)
    print('LAYER 1 — 容器/解码校验和（变砖第一防线）')
    print('=' * 72)
    print('container sum32 (stock) ', hex(sum32(s_raw)))
    print('container sum32 (patch) ', hex(sum32(p_raw)), '  ', 'OK (==0)' if sum32(p_raw) == 0 else 'FAIL')
    print('decoded   sum32 (patch) ', hex(sum32(p_dec)), '  ', 'OK (==0)' if sum32(p_dec) == 0 else 'FAIL')
    print('decoded len equal        ', len(s_dec) == len(p_dec))
    layer1_ok = sum32(p_raw) == 0 and sum32(p_dec) == 0 and len(s_dec) == len(p_dec)

    diff = np.flatnonzero(np.frombuffer(s_dec, 'u1') != np.frombuffer(p_dec, 'u1'))
    rows = section_rows(p_dec)
    secs = sorted({r['name'] for r in rows for o in diff if r['start'] <= o < r['end']})
    print(f'decoded bytes changed    {len(diff)}  (sections: {secs})')

    rt = lambda dec: bytes(dec[0x10870:0x10c5e30])
    S, P = rt(s_dec), rt(p_dec)

    def run(rtos, tone, stage=1, sub=0, hdr=0):
        e, obj, info, si = setup(stage=stage, rtos=rtos)
        g = e.r32(obj + 0x17c)
        def x(e, st):
            e.w8(st + 0x797, sub)
            e.w8(st + 0x788, hdr)
        out = make(e, obj, info, si, tone, stage=stage, extra=x)
        u = lambda a: np.frombuffer(bytes(e.u.mem_read(a, 512)), '<u2').astype(int)
        return out, [u(g + o) for o in (0x2a08, 0x2c08, 0x2e08)], u(g), e.u.mem_read(si + 0x38a98, 1)[0], bytes(e.u.mem_read(obj + 0x1f0, 2))

    ok = layer1_ok

    print()
    print('=' * 72)
    print('LAYER 2 — 未改动模式（应为 stock 字节级一致）')
    print('=' * 72)
    for stage in (1, 0):
        # Standard (tone 11) is now a replaced slot (500T), so it is NOT expected to stay stock.
        for tone, name in ((13, 'Monotone'), (17, 'Positive'), (18, 'Bleach'), (22, 'Negative')):
            same = run(S, tone, stage)[0] == run(P, tone, stage)[0]
            ok &= same
            print(f'stage {stage} {name}: identical to stock {same}')

    print()
    print('=' * 72)
    print('LAYER 3 — 5 个替换槽位的 composite 曲线 + matrix')
    print('=' * 72)
    for (name, tone, *_), fit in zip(MODES, fits):
        for sub, hdr in ((0, 0), (2, 0), (0, 1), (0, 2)) if tone == 20 or tone == 21 else ((0, 0),):
            o, comp, base, sel, hdrfld = run(P, tone, 1, sub, hdr)
            want = [np.interp(np.clip(base / 64, 0, 255), np.arange(256), np.array(c)) for c in fit['presets'][0]['curves']]
            err = max(np.abs(comp[i] - want[i]).max() for i in range(3))
            q = q13_matrix(fit['matrix']).ravel().tolist()
            std = run(P, 11, 1)[0]
            nd = np.flatnonzero(np.frombuffer(o, 'u1') != np.frombuffer(std, 'u1'))
            good = err <= 2
            ok &= good
            print(f'{name:10s} tone={tone} sub{sub} 0x788={hdr}: selector {sel}, curve err {err:.0f}/16384, '
                  f'hdr field {hdrfld.hex()}, R2Y diff vs Standard {len(nd)} bytes {"OK" if good else "FAIL"}')

    # matrix read-back (record look matrix == fitted q13), read directly from decoded patched image
    print()
    print('matrix read-back (record = fitted q13):')
    from gr3patch import RECORDS, BASE, DSRC, DDST, DLEN
    rtos0 = {r['name']: r for r in rows}['RTOS']['start'] + 16
    def at(dec, a):
        if DDST <= a < DDST + DLEN:
            a = DSRC + a - DDST
        return rtos0 + a - BASE
    W = lambda dec, a: struct.unpack('<I', dec[at(dec, a):at(dec, a) + 4])[0]
    for (name, tone, slots, donor, sel, cids), fit in zip(MODES, fits):
        rec = W(p_dec, RECORDS + 4 * donor)
        mat = W(p_dec, rec + 4)
        q = q13_matrix(fit['matrix']).ravel().tolist()
        got = struct.unpack('<9h', p_dec[at(p_dec, mat):at(p_dec, mat) + 18])
        match = list(got) == [round(v) for v in q]
        ok &= match
        print(f'  {name:10s} record={rec:#x} matrix@={mat:#x}  match={match}')

    print()
    print('=' * 72)
    print('RESULT:', 'ALL OK' if ok else 'FAILURES')
    print('=' * 72)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
