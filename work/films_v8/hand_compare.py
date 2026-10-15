"""Hand photos (photo-v8 R0011842 Vivid/Ektar, R0011843 Cross/Portra): v7 (simulated by undoing CCA1 on the camera
JPEG) vs v8 camera JPEG vs the spektrafilm target rendered from the DNG; plus mean skin Lab / hue per variant."""
import sys, json; sys.path.insert(0, '.')
import numpy as np, cv2, rawpy, colour
from cube_fit import load_target
D = '../photo-v8/'
OUT = sys.argv[1] if len(sys.argv) > 1 else 'work/films_v8/hand_compare.jpg'
mats = json.load(open('work/films_v8/cca1_mats.json'))
F3 = 'work/films_v3/fits/'
EK = np.load('work/films_v8/EK.npy')
shots = [('R0011842', 'Ektar (Vivid)', F3 + 'ektar_b1n3.json'), ('R0011843', 'Portra (Cross)', F3 + 'portra_b4n3.json')]
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
rows = []
for n, name, fp in shots:
    jpg = cv2.cvtColor(cv2.imread(D + n + '.JPG'), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    C = np.array(mats[fp]['q512']) / 512
    v7 = np.clip(jpg @ np.linalg.inv(C).T, 0, 1)
    f = json.load(open(fp))
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, user_flip=0).astype(np.float32) / 65535
    lin = cv2.resize(lin, (jpg.shape[1], jpg.shape[0]), interpolation=cv2.INTER_AREA)
    L = lin.reshape(-1, 3) @ EK.T * 0.18 / 7.8
    tgt = load_target(f['presets'][0]['spec'], 'vlog', 0)(L).reshape(jpg.shape)
    # skin region: the forearm, centre-left of the frame
    h, w = jpg.shape[:2]; y0, y1, x0, x1 = int(h * 0.55), int(h * 0.75), int(w * 0.25), int(w * 0.55)
    st = []
    for nm, im in (('v7 (sim)', v7), ('v8 camera', jpg), ('film target', tgt)):
        p = lab(im[y0:y1, x0:x1].reshape(-1, 3).mean(0))
        st.append((nm, p))
        print(f'{name:16s} {nm:12s} L {p[0]:5.1f}  a {p[1]:5.1f}  b {p[2]:5.1f}  hue {np.degrees(np.arctan2(p[2], p[1])):5.1f}  chroma {np.hypot(p[1], p[2]):5.1f}')
    sm = lambda x: cv2.resize(x[:, :], (900, 600), interpolation=cv2.INTER_AREA)
    tiles = []
    for (nm, _), im in zip(st, (v7, jpg, tgt)):
        t = (sm(im) * 255).clip(0, 255).astype(np.uint8)[:, :, ::-1].copy()
        cv2.rectangle(t, (int(900 * 0.25), int(600 * 0.55)), (int(900 * 0.55), int(600 * 0.75)), (255, 255, 255), 1)
        cv2.putText(t, f'{name} - {nm}', (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        tiles.append(t)
    rows.append(np.hstack(tiles))
cv2.imwrite(OUT, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
