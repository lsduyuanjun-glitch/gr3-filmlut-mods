"""Films v16 fits (FINDINGS §33): the v15 cube films + MultiAxial hue sectors (12 sector matrices on the post-look-matrix
signal, GR IV geometry = GR4-LUTSmith's HUE_BOUNDS, confirmed on the GR III in §30b).
Per film: (1) sectors on the v15 fit (matrix / curves / post fixed), (2) lab_fit (matrix, post, curve corrections) with
those sectors in the model, (3) sectors again. Sectors are stored as the firmware stores them: off-diagonals in steps of
4/1024 (int8), diagonal = 1024 - row sum. Scores are with the curves as the firmware stores them (33 knots).
Writes work/films_v16/fits/<key>.json (v15 fit + 'hue_q10' + 'v16' scores).
Usage (from re-tools): work/films_v16/refit16.py ~/dev/GR4-LUTSmith [key ...]"""
import sys, json, importlib.util; sys.path.insert(0, '.')
import numpy as np, colour
from scipy.optimize import least_squares
import cube_fit as cf
from cube_fit import BASE, K, samples, warm_samples, target_of, de2000
import lab_fit as LF
from film_cave import knots_of, expand
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
F12, F11, F14 = 'work/films_v12/fits/', 'work/films_v11/fits/', 'work/films_v14/fits/'
FILMS = {'portra': (F12 + 'portra_b4n3_lab.json', 4), 'ektar': (F12 + 'ektar_b1n3_lab.json', 1),
         'gold': (F12 + 'gold_b4n3_lab.json', 4), 'pro400h': (F12 + 'pro400h_own_b4n3_lab.json', 4),
         'vision3': (F11 + 'vision3250d_2383_b4n3_lab.json', 4), 'classicneg': (F12 + 'classicneg_b4n3_lab.json', 4),
         'vision3500t': (F14 + 'vision3500t_2383_b4n3_lab.json', 4)}
chart = np.load('work/films_v10/camera_chart_L.npy')
warm = warm_samples(n=1200, seed=11); Lg, _, cc = samples(seed=7)
SETS = [('general', Lg[600:]), ('warm', warm), ('ColorChecker', cc), ('camera chart', chart)]
KINK = ls.hue_kinks()
B = np.array([ls.hue_matrices(e.reshape(12, 3)).ravel() for e in np.eye(36)]) - ls.hue_matrices(np.zeros((12, 3))).ravel()
M0 = ls.hue_matrices(np.zeros((12, 3))).ravel()
HQ = None                                   # sector matrices (12,3,3) / 1024 in use by the patched model


def quant4(mats):
    """Firmware storage: off-diagonals round(x/4)*4 (int8 steps), diagonal = 1024 - row sum."""
    q = np.rint(np.asarray(mats) * 1024 / 4).astype(int) * 4
    for g in range(12):
        for r in range(3):
            q[g, r, r] = 1024 - (q[g, r].sum() - q[g, r, r])
    off = q.copy(); [np.fill_diagonal(off[g], 0) for g in range(12)]
    assert np.abs(off).max() <= 4 * 127 and np.abs(off.sum(2)).max() <= 4 * 127, 'sector matrix out of int8 range'
    return q


def model(M, curves, L):                    # cube_fit.model + sectors between look matrix and base gamma
    z = (K * L) @ np.asarray(M).T
    if HQ is not None:
        z = ls.hue_apply_q(z, HQ * 1024, ls.HUE_BOUNDS)
    b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
    return np.stack([np.interp(np.clip(b[:, c] / 64, 0, 255), np.arange(256), curves[c]) for c in range(3)], 1) / 16384


LF.model = model                            # lab_fit renders through this


def render(f, knots=True):
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']] if knots else [np.array(c, float) for c in f['presets'][0]['curves']]
    P = np.array(f['post_q512']) / 512; M = np.array(f['matrix'])
    return lambda X: np.clip(model(M, cv, X) @ P.T, 0, 1)


def scores(f, T):
    out = []
    for nm, X in SETS:
        t = T(X); u = t.min(1) > 0.02 if nm == 'camera chart' else np.ones(len(X), bool)
        out.append(round(float(de2000(render(f)(X)[u], t[u]).mean()), 3))
    return out


def fit_sectors(f, boost, T):
    global HQ
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost); tl = LF.lab(T(L)); sw = np.sqrt(w / w.mean()); n = np.sqrt(len(L))
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]
    P = np.array(f['post_q512']) / 512; M = np.array(f['matrix'])

    def res(d):
        global HQ
        HQ = ls.hue_matrices(d.reshape(12, 3))
        e = sw * colour.delta_E(LF.lab(np.clip(model(M, cv, L) @ P.T, 0, 1)), tl, method='CIE 2000')
        pen = np.r_[np.sqrt(ls.HUE_KINKS[0] / 12) * KINK @ d, np.sqrt(ls.HUE_RIDGE / 12) * d,
                    np.sqrt(ls.HUE_RANGE) * np.maximum(np.abs(M0 + d @ B) - ls.HUE_LIMIT, 0)]
        return np.r_[e, n * pen]
    d = least_squares(res, np.zeros(36), x_scale=0.05, max_nfev=40).x
    HQ = quant4(ls.hue_matrices(d.reshape(12, 3))) / 1024
    return HQ


fmt = lambda s: ' / '.join(f'{x:.2f}' for x in s)
keys = sys.argv[2:] or list(FILMS)
for key in keys:
    fp, boost = FILMS[key]
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    HQ = None; s0 = scores(f, T)
    H1 = fit_sectors(f, boost, T); s1 = scores(f, T)
    g = dict(f, cca1_q512=f['post_q512'])
    g, _, _ = LF.lab_fit(g, boost)            # matrix / post / curves with H1 in the model
    H2 = fit_sectors(g, boost, T); s2 = scores(g, T)
    best, hq, sb = (g, H2, s2) if s2[0] < s1[0] else (f, H1, s1)
    HQ = hq
    out = dict(best, hue_q10=np.rint(hq * 1024).astype(int).tolist(),
               v16=dict(v15=s0, sectors=s1, joint=s2, kept='joint' if best is g else 'sectors'))
    json.dump(out, open(f'work/films_v16/fits/{key}.json', 'w'))
    print(f'{key:12s} v15 {fmt(s0)} | + sectors {fmt(s1)} | joint {fmt(s2)} -> {out["v16"]["kept"]}', flush=True)
