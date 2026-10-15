"""Hue-chart patch extraction that tolerates camera movement: finds the 4 white corner markers, fits a homography
from chart coordinates (make_hue_chart.py, 3840x2160 layout) and samples the central part of each of 7x36 cells."""
import numpy as np, cv2, rawpy

W, H = 3840, 2160
m = int(H * 0.06); gx0, gy0, gx1, gy1 = m * 2, m * 2, W - m * 2, H - m * 2
CW, CH = (gx1 - gx0) / 36, (gy1 - gy0) / 7
MARK = np.array([(m, m), (W - m, m), (m, H - m), (W - m, H - m)], np.float32)   # marker centres TL TR BL BR


def markers(gray):
    """gray: float 0..1 display-encoded image. Returns TL, TR, BL, BR marker centres."""
    h, w = gray.shape
    cand = []
    for th in (0.3, 0.4, 0.5, 0.6):                 # markers are the only square bright blobs (cells are 1:2.8)
        n, lab, st, cen = cv2.connectedComponentsWithStats((gray > th).astype(np.uint8))
        for i in range(1, n):
            x, y, bw, bh, a = st[i]
            if h * w * 4e-4 < a < h * w * 0.01 and 0.75 < bw / bh < 1.33 and a > 0.8 * bw * bh:
                cand.append(cen[i])
        if len(cand) >= 4:
            break
    cand = np.array(cand)
    assert len(cand) >= 4, len(cand)
    s, d = cand.sum(1), cand[:, 0] - cand[:, 1]
    return np.array([cand[s.argmin()], cand[d.argmax()], cand[d.argmin()], cand[s.argmax()]], np.float32)


def sample(img, gray):
    Hm = cv2.getPerspectiveTransform(MARK, markers(gray))
    out = np.zeros((7, 36, 3))
    for r in range(7):
        for c in range(36):
            xs = np.linspace(gx0 + (c + 0.3) * CW, gx0 + (c + 0.7) * CW, 6)
            ys = np.linspace(gy0 + (r + 0.3) * CH, gy0 + (r + 0.7) * CH, 6)
            P = np.array([(x, y) for x in xs for y in ys], np.float32)[None]
            q = cv2.perspectiveTransform(P, Hm)[0]
            vals = [img[int(round(y)), int(round(x))] for x, y in q]
            out[r, c] = np.median(vals, 0)
    return out


def load(path_noext):
    jpg = cv2.cvtColor(cv2.imread(path_noext + '.JPG'), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    jpg = cv2.blur(jpg, (5, 5))
    J = sample(jpg, jpg.mean(2))
    with rawpy.imread(path_noext + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, user_flip=0).astype(np.float32) / 65535
    lin = cv2.blur(lin, (5, 5))
    g = lin.mean(2)
    L = sample(lin, (g / np.percentile(g, 99.9)) ** (1 / 2.2))
    return J, L
