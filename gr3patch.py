"""Offline GR III fw 2.10 look-patch builder (proof of concept, never touches a camera)."""
import sys, struct, hashlib
import codec_path  # noqa: F401  (gr4_editor from the gr-custom-tool submodule)
from gr4_editor.codec.container import inspect_container, repair_last_word, sum32
from gr4_editor.codec.frames import decode_payload, section_rows, framed_container
from gr4_editor.firmware import _repack_frames

BASE, DSRC, DDST, DLEN = 0x53000000, 0x5407B540, 0x55000000, 0x3A080
EXPECT_SHA = 'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4'

# 各机型官方固件 SHA（按 model id 识别）。GR IIIx 系列共用 fwdc243b 1.70。
MODEL_SHA = {
    'gr3':     'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4',
    'gr3hdf':  'd6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4',
    'gr3x':    'aa8e3ae1349d94e83be381c20530e41d5e57b75c27ef24ba81c7b017d6c11592',
    'gr3xhdf': 'aa8e3ae1349d94e83be381c20530e41d5e57b75c27ef24ba81c7b017d6c11592',
}

class Image:
    def __init__(self, path, model='gr3'):
        self.model = model
        self.candidate = open(path, 'rb').read()
        expect = MODEL_SHA.get(model, EXPECT_SHA)
        got = hashlib.sha256(self.candidate).hexdigest()
        if got != expect:
            raise SystemExit(
                f'unexpected input firmware: model={model} expects {expect[:16]}..., got {got[:16]}...')
        info = inspect_container(self.candidate)
        self.original, _ = decode_payload(self.candidate[128:info['payload_end']], info['decoded_size'])
        rows = {r['name']: r for r in section_rows(self.original)}
        self.rtos0 = rows['RTOS']['start'] + 16
        self.rtos_end = rows['RTOS']['end']
        self.target = bytearray(self.original)
        # GR IIIx 机型：加载地址重映射表（gr3_addr_map.gr3x_of 做地址 → GR IIIx 地址）
        self._remap = None
        if model in ('gr3x', 'gr3xhdf'):
            import gr3_addr_map as _am
            self._remap = _am

    def off(self, addr):
        if DDST <= addr < DDST + DLEN:
            addr = DSRC + addr - DDST
        if self._remap is not None:
            # GR IIIx：把 GR III 2.10 地址重定位到 GR IIIx 1.70
            new = self._remap.gr3x_of(addr)
            if new is None:
                raise SystemExit(
                    f'GR IIIx: address 0x{addr:08X} not yet relocated '
                    f'(见 work/gr3x_addr_map.json，需先跑 relocate_gr3x.py 补全)')
            addr = new
        o = self.rtos0 + addr - BASE
        assert self.rtos0 <= o < self.rtos_end, f'addr 0x{addr:08X} out of RTOS'
        return o

    def read(self, addr, n): o = self.off(addr); return bytes(self.target[o:o + n])
    def write(self, addr, data): o = self.off(addr); self.target[o:o + len(data)] = data
    def word(self, addr): return struct.unpack('<I', self.read(addr, 4))[0]

    def rtos(self): return bytes(self.target[self.rtos0:self.rtos_end])

    def grow(self, n):
        """Append n zero bytes to the RTOS payload and bump its section length (growth codec, FINDINGS §42).

        The appended region is the 'extension': code/tables that no longer fit the
        stock caves go here.  BOOT loads RTOS by its stored section size, so a grown
        image boots the extension as read-only mapped memory (author §42a probe passed).
        n must be word-aligned (multiple of 4).  Returns the extension's load address.

        Implementation: the RTOS section header's length field lives at decoded offset
        (RTOS_start + 12) and must be increased so section_rows parses the grown layout;
        the bytes are inserted at the RTOS payload end (self.rtos_end).
        """
        assert n % 4 == 0, 'growth must be word-aligned'
        rows = {r['name']: r for r in section_rows(self.target)}
        rtos = rows['RTOS']
        ext_base = BASE + (rtos['end'] - (rtos['start'] + 16))  # load address of the extension = BASE + old payload length
        # insert n zero bytes at the RTOS payload end, and bump the length field
        self.target = self.target[:rtos['end']] + bytearray(n) + self.target[rtos['end']:]
        hdr_len_off = rtos['start'] + 12
        struct.pack_into('<I', self.target, hdr_len_off, struct.unpack_from('<I', self.target, hdr_len_off)[0] + n)
        self.rtos_end += n
        self._grown = True
        # 记录 grow 量：ICONBIN 等下游段在 target 里整体后移 n 字节，
        # make_icons.iconbin 需要据此修正像素写入偏移（否则 film icon 会写到偏前 n 字节的位置）
        self._grow_bytes = getattr(self, '_grow_bytes', 0) + n
        return ext_base

    def build(self):
        tgt = repair_last_word(bytes(self.target))
        assert sum32(tgt) == 0
        growth = getattr(self, '_grown', False)
        payload, report = _repack_frames(self.candidate, self.original, tgt, growth=growth)
        out = framed_container(self.candidate, payload, tgt)
        return out, report

# --- look helpers -------------------------------------------------------
RECORDS = 0x55018D94                       # per-slot look record table (RAM, ROM-initialised)
SLOT = dict(standard=11, vivid=12, monotone=13, soft_mono=14, hard_mono=15, hicon_bw=16,
            positive=17, bleach=18, retro=19, hdr=20, cross=21, negative=25)

def set_look_matrix(img, slot, m):
    """m: 3x3 floats, rows=output R,G,B. Stored s16 Q13 row-major."""
    rec = img.word(RECORDS + 4 * slot)
    ptr = img.word(rec + 4)
    vals = [round(v * 8192) for row in m for v in row]
    assert all(-32768 <= v < 32768 for v in vals)
    img.write(ptr, struct.pack('<9h', *vals))
    return ptr

if __name__ == '__main__':
    img = Image(sys.argv[1])
    # demo: warm, slightly muted "portra-like" matrix on the Retro slot
    m = [[1.10, -0.05, -0.05], [0.02, 0.95, 0.03], [-0.04, 0.02, 0.92 + 0.10]]
    p = set_look_matrix(img, SLOT['retro'], m)
    out, rep = img.build()
    open(sys.argv[2], 'wb').write(out)
    print('patched matrix at', hex(p), rep)
