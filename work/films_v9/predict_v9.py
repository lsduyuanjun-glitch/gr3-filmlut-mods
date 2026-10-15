"""Predict v9 (joint fits) on the photo-v8 hue chart and on the forearm patch, vs v8 model and the film target."""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, colour, cv2, rawpy
from cube_fit import load_target, model, de2000
from chart import load
D = '../photo-v8/'
EK = np.load('work/films_v8/EK.npy')
mats = json.load(open('work/films_v8/cca1_mats.json'))
F3, F4, F9 = 'work/films_v3/fits/', 'work/films_v4/fits/', 'work/films_v9/fits/'
films = [('R0011834', 'Ektar', F3 + 'ektar_b1n3.json'), ('R0011838', 'Gold', F3 + 'gold_b4n3.json'),
         ('R0011839', 'Pro 400H', F4 + 'pro400h_own_b4n3.json'), ('R0011840', 'Portra', F3 + 'portra_b4n3.json')]
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
def run(fp, L, C):
    f = json.load(open(fp)); return np.clip(model(np.array(f['matrix']), [np.array(c) for c in f['presets'][0]['curves']], L) @ C.T, 0, 1)
for n, name, fp in films:
    jp = F9 + fp.split('/')[-1].replace('.json', '_joint.json')
    J, Lr = load(D + n); L = Lr.reshape(-1, 3) @ EK.T * 0.18 / 7.8
    f8 = json.load(open(fp)); t = load_target(f8['presets'][0]['spec'], 'vlog', 0)(L)
    m8 = run(fp, L, np.array(mats[fp]['q512']) / 512); m9 = run(jp, L, np.array(json.load(open(jp))['cca1_q512']) / 512)
    cam = J.reshape(-1, 3)
    use = (cam.max(1) < 0.97) & (t.min(1) > 0.02) & (cam.min(1) > 0.02)
    tl = lab(t); Ch = np.hypot(tl[:, 1], tl[:, 2]); h = np.degrees(np.arctan2(tl[:, 2], tl[:, 1])) % 360
    warm = use & (Ch > 20) & (h > 30) & (h < 100)
    d = lambda x, k: de2000(x[k], t[k]).mean()
    print(f'{name:9s} hue chart vs target: v8 model {d(m8, use):.2f} (warm {d(m8, warm):.2f})  v9 model {d(m9, use):.2f} (warm {d(m9, warm):.2f})')
for n, name, fp in [('R0011842', 'Ektar', F3 + 'ektar_b1n3.json'), ('R0011843', 'Portra', F3 + 'portra_b4n3.json')]:
    jp = F9 + fp.split('/')[-1].replace('.json', '_joint.json')
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, user_flip=0, half_size=True).astype(np.float32) / 65535
    h, w = lin.shape[:2]; patch = lin[int(h * .55):int(h * .75), int(w * .25):int(w * .55)].reshape(-1, 3)
    L = patch[::50] @ EK.T * 0.18 / 7.8
    f8 = json.load(open(fp)); t = load_target(f8['presets'][0]['spec'], 'vlog', 0)(L)
    m8 = run(fp, L, np.array(mats[fp]['q512']) / 512); m9 = run(jp, L, np.array(json.load(open(jp))['cca1_q512']) / 512)
    for nm, x in (('v8 model', m8), ('v9 model', m9), ('target', t)):
        p = lab(x.mean(0)); print(f'{name:7s} skin {nm:9s} hue {np.degrees(np.arctan2(p[2], p[1])):5.1f} chroma {np.hypot(p[1], p[2]):5.1f} L {p[0]:5.1f}   dE to target {de2000(x, t).mean():.2f}')
