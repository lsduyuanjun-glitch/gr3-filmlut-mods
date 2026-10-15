"""v15 vs v16 on earlier real RAW files: every film rendered from the DNG (rawpy linear, camera WB, EK from the
photo-v10 Standard chart, exposure = Standard model fitted to the camera's own JPG), scored against the film's target
(spektrafilm LUT on the same scene-linear pixels). Also how far v16 moves away from v15 (visibility of the change),
and a preview sheet per scene (rows: films; columns: v15 | v16 | target).
Scenes: photo-v13 R0011936-38 (real scenes) and photo-v10 R0011890 (hue chart, Daylight WB).
Usage (from re-tools): work/films_v16/check_prev.py ~/dev/GR4-LUTSmith"""
import sys, json, importlib.util; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, K, STD_LOOK, de2000, target_of
from chart import load
from film_cave import knots_of, expand
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
D10 = '../photo-v10/'
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ a


def look(f, hue):
    cv = f['presets'][0]['curves']
    cv = [np.array(c, float) for c in cv] if 'spec' in f['presets'][0] and str(f['presets'][0]['spec']).startswith('gr4') \
        else [expand(knots_of(c)) for c in cv]
    M, P = np.array(f['matrix']), np.array(f['post_q512']) / 512
    H = np.array(f['hue_q10']) if hue and 'hue_q10' in f else None
    def r(L):
        z = (K * L) @ M.T
        if H is not None:
            z = ls.hue_apply_q(z, H, ls.HUE_BOUNDS)
        b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
        return np.clip(np.stack([np.interp(np.clip(b[:, c] / 64, 0, 255), np.arange(256), cv[c]) for c in range(3)], 1) / 16384 @ P.T, 0, 1)
    return r


F12, F11, F14, F16 = 'work/films_v12/fits/', 'work/films_v11/fits/', 'work/films_v14/fits/', 'work/films_v16/fits/'
FILMS = [('Portra 400', F12 + 'portra_b4n3_lab.json', 'portra'), ('Ektar 100', F12 + 'ektar_b1n3_lab.json', 'ektar'),
         ('Gold 200', F12 + 'gold_b4n3_lab.json', 'gold'), ('Pro 400H', F12 + 'pro400h_own_b4n3_lab.json', 'pro400h'),
         ('Vision3 250D', F11 + 'vision3250d_2383_b4n3_lab.json', 'vision3'),
         ('Classic Neg', F12 + 'classicneg_b4n3_lab.json', 'classicneg'),
         ('Vision3 500T', F14 + 'vision3500t_2383_b4n3_lab.json', 'vision3500t'),
         ('Cinema Y', F14 + 'cinema_yellow.json', 'cinema_yellow'), ('Cinema G', F14 + 'cinema_green.json', 'cinema_green')]
W, H = 480, 320


def scene(path):
    with rawpy.imread(path + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    jpg = cv2.cvtColor(cv2.imread(path + '.JPG'), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    lin = cv2.resize(lin, (W, H), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    js = cv2.resize(jpg, (W, H), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    L0 = lin @ EK.T * 0.18 / 7.8
    std = look(dict(matrix=STD_LOOK.tolist(), post_q512=(np.eye(3) * 512).tolist(),
                    presets=[dict(spec='gr4:std', curves=[np.minimum(np.arange(256) * 64.0, 16383).tolist()] * 3)]), False)
    use = (js.max(1) < 0.97) & (js.min(1) > 0.02)
    g = least_squares(lambda p: (std(L0[use] * np.exp(p[0])) - js[use]).ravel(), [0.0], loss='soft_l1', f_scale=0.05).x[0]
    return L0 * np.exp(g), use


rows = []
for name, sc in (('chart v10', D10 + 'R0011890'), ('scene 36', '../photo-v13/R0011936'), ('scene 37', '../photo-v13/R0011937'),
                 ('scene 38', '../photo-v13/R0011938')):
    L, use = scene(sc)
    sheet = []
    print(f'\n{name}: mean dE2000 vs film target, v15 -> v16 | v16 vs v15 mean / p95')
    for fname, fp15, key in FILMS:
        f15, f16 = json.load(open(fp15)), json.load(open(F16 + key + '.json'))
        a15, a16 = look(f15, False)(L), look(f16, True)(L)
        if 'cinema' in key:
            t = None
            ch = de2000(a15, a16)
            print(f'  {fname:13s} (target = GR IV render, not emulated here)         | change {ch[use].mean():.2f} / {np.percentile(ch[use], 95):.2f}')
        else:
            t = target_of(f16['presets'][0])(L)
            e15, e16, ch = de2000(a15, t), de2000(a16, t), de2000(a15, a16)
            print(f'  {fname:13s} {e15[use].mean():.2f} -> {e16[use].mean():.2f}  (p95 {np.percentile(e15[use], 95):.2f} -> '
                  f'{np.percentile(e16[use], 95):.2f}) | change {ch[use].mean():.2f} / {np.percentile(ch[use], 95):.2f}')
            rows.append((name, fname, e15[use].mean(), e16[use].mean()))
        im = [x.reshape(H, W, 3) for x in (a15, a16, t if t is not None else np.zeros_like(a15))]
        row = np.ascontiguousarray((np.concatenate(im, 1) * 255).clip(0, 255).astype(np.uint8))
        cv2.putText(row, fname, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        sheet.append(row)
    out = np.concatenate(sheet, 0)
    cv2.imwrite(f'work/films_v16/preview_{name.replace(" ", "_")}.jpg', cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
r = np.array([(x[2], x[3]) for x in rows])
print(f'\nall scenes x 7 cube films: v15 {r[:, 0].mean():.2f} -> v16 {r[:, 1].mean():.2f}; v16 better in {(r[:, 1] < r[:, 0]).sum()}/{len(r)}')
