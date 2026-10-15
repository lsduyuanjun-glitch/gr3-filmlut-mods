"""Films v16 on camera (photo-v16, hue chart, Daylight WB): which look did the camera apply, and do the hue sectors act
as modelled? Each JPG is compared against Standard and every film both as v15 (no hue sectors) and as v16 (with the
12 sector matrices). (Scaling every sector matrix by a GR IV level factor is the same as an exposure change here, so
the level question cannot be tested on this chart.) Same method as films_v13/check_v13.py (rawpy linear, ECC alignment, 375x250, EK from the photo-v10
Standard chart, per-shot exposure gain + radial lens-shading gain fitted per look, edges / clipped pixels left out).
For the cube films also camera vs film target (spektrafilm LUT) next to v15/v16 model vs target.
Usage (from re-tools): work/films_v16/check_v16.py ~/dev/GR4-LUTSmith"""
import sys, json, glob, os, importlib.util; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, K, STD_LOOK, de2000, target_of
from chart import load
from film_cave import knots_of, expand
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
D10, D = '../photo-v10/', '../photo-v16/'
W, H = 375, 250

bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ a


def pair(n):
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    jpg = cv2.cvtColor(cv2.imread(D + n + '.JPG'), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    h, w = lin.shape[:2]; y0, x0 = (h - 2000) // 2, (w - 3000) // 2
    lin = lin[y0:y0 + 2000, x0:x0 + 3000]
    jl = cv2.resize(jpg, (3000, 2000), interpolation=cv2.INTER_AREA)
    s = lambda g: cv2.resize(g, (750, 500), interpolation=cv2.INTER_AREA).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    cc, warp = cv2.findTransformECC(s(lin.mean(2) ** (1 / 2.2)), s(jl.mean(2)), warp, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    warp[:, 2] *= 4
    jl = cv2.warpAffine(jl, warp, (3000, 2000), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    small = lambda x: cv2.resize(x, (W, H), interpolation=cv2.INTER_AREA)
    js = small(jl)
    g = js.mean(2)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    flat = cv2.dilate((grad > 0.15).astype(np.uint8), np.ones((3, 3))) == 0
    flat[:4], flat[-4:], flat[:, :4], flat[:, -4:] = False, False, False, False
    return small(lin).reshape(-1, 3), js.reshape(-1, 3), flat.ravel(), cc


def look(f, hue, scale=1.0):          # as check_prev.py; scale = GR IV level factor (16-l)/16 on the sector matrices
    cv = f['presets'][0]['curves']
    cv = [np.array(c, float) for c in cv] if str(f['presets'][0].get('spec', '')).startswith('gr4') \
        else [expand(knots_of(c)) for c in cv]
    M, P = np.array(f['matrix']), np.array(f['post_q512']) / 512
    Hq = np.array(f['hue_q10']) * scale if hue and 'hue_q10' in f else None
    def r(L):
        z = (K * L) @ M.T
        if Hq is not None:
            z = ls.hue_apply_q(z, Hq, ls.HUE_BOUNDS)
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
ident = np.minimum(np.arange(256) * 64.0, 16383)
LOOKS = {('Standard', ''): look(dict(matrix=STD_LOOK.tolist(), post_q512=(np.eye(3) * 512).tolist(),
                                     presets=[dict(spec='gr4:std', curves=[ident.tolist()] * 3)]), False)}
TARGETS = {}
for name, fp15, key in FILMS:
    f15, f16 = json.load(open(fp15)), json.load(open(F16 + key + '.json'))
    LOOKS[(name, 'v15')] = look(f15, False)
    LOOKS[(name, 'v16')] = look(f16, True)
    if 'cinema' not in key:
        TARGETS[name] = target_of(f16['presets'][0])

yy, xx = np.mgrid[0:H, 0:W]
r2 = (((xx - W / 2 + 0.5) ** 2 + (yy - H / 2 + 0.5) ** 2) / ((W / 2) ** 2 + (H / 2) ** 2)).ravel()
# what was selected (photo-v16, 2026-10-10: list order from the camera; EXIF ImageTone only names the stock modes)
EXPECT = dict(zip(['R00%05d' % i for i in range(11993, 12006)],
                  ['Standard', 'Vivid', 'Negative', 'Positive', 'Cinema Y', 'Cinema G', 'Vision3 500T', 'Portra 400',
                   'Ektar 100', 'Gold 200', 'Pro 400H', 'Vision3 250D', 'Classic Neg']))
shots = sorted(os.path.basename(p)[:-4] for p in glob.glob(D + '*.DNG'))
print('mean dE2000 camera JPG vs look (exposure + lens-shading gain fitted per look)')
print(f'{"shot":9s} {"best fitting look":22s} {"dE":>5s} | {"v15":>5s} {"v16":>5s} {"2nd film":>13s} {"dE":>5s} | '
      f'cam-tgt v15-tgt v16-tgt   px  ECC')
summary = []
for n in shots:
    lin, cam, flat, cc = pair(n)
    L0 = lin @ EK.T * 0.18 / 7.8
    use = flat & (cam.max(1) < 0.97) & (cam.min(1) > 0.02) & (lin.max(1) < 0.9)
    res, Lf = {}, {}
    for k, f in LOOKS.items():
        Lp = lambda p: L0 * (np.exp(p[0]) * (1 + p[1] * r2 + p[2] * r2 ** 2))[:, None]
        p = least_squares(lambda p: (f(Lp(p)[use]) - cam[use]).ravel(), [0, 0, 0], loss='soft_l1', f_scale=0.05).x
        Lf[k] = Lp(p)
        res[k] = de2000(cam, f(Lf[k]))[use].mean()
    best = min(res, key=res.get)
    name = EXPECT.get(n, best[0])
    other = min((v, k[0]) for k, v in res.items() if k[0] != name)
    v15, v16 = res.get((name, 'v15'), np.nan), res.get((name, 'v16'), np.nan)
    extra = ''
    if name in TARGETS:
        t = TARGETS[name](Lf[(name, 'v16')])
        u = use & (t.min(1) > 0.02) & (t.max(1) < 0.98)
        e = [de2000(x, t)[u].mean() for x in (cam, LOOKS[(name, 'v15')](Lf[(name, 'v16')]), LOOKS[(name, 'v16')](Lf[(name, 'v16')]))]
        extra = f'{e[0]:7.2f} {e[1]:7.2f} {e[2]:7.2f} {u.sum():4d}'
        summary.append((name, v15, v16, *e))
    elif (name, 'v16') in LOOKS:
        summary.append((name, v15, v16, np.nan, np.nan, np.nan))
    flag = '' if best[0] == name else f'  <- selected {name}, fits {best[0]} {best[1]} best'
    print(f'{n:9s} {best[0] + " " + best[1]:22s} {res[best]:5.2f} | {v15:5.2f} {v16:5.2f} {other[1]:>13s} {other[0]:5.2f} | '
          f'{extra:30s} {cc:.3f}{flag}')
s = np.array([x[1:] for x in summary], float)
print('(v15/v16/2nd film/target columns are for the selected mode; stock Vivid/Negative/Positive have no model)')
print(f'\nfilm shots: camera vs v15 model {np.nanmean(s[:, 0]):.2f}, vs v16 model {np.nanmean(s[:, 1]):.2f}; '
      f'v16 closer in {(s[:, 1] < s[:, 0]).sum()}/{len(s)}')
c = ~np.isnan(s[:, 2])
print(f'cube films vs target: camera {s[c, 2].mean():.2f}, v15 model {s[c, 3].mean():.2f}, v16 model {s[c, 4].mean():.2f}')
