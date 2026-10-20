#!/usr/bin/env python3
"""离线解锁码校验 —— 免费/付费胶片门控。

设计目标（轻量、离线、可本地验证）：
- 免费款固定开放（默认 Kodak 5207）。
- 付费款需要解锁码，解锁码是「胶片 key 集合 + 版本」的 ed25519 离线签名。
- 校验不联网：买家拿到解锁码后在本地输入，工具用内置公钥验签，
  通过则把已解锁胶片写入本地 license.json，永久生效。
- 解锁码不绑定机器（避免做机器码复杂度）。

密钥说明（非对称 ed25519）：
- 私钥只在 Duccio 自己手里（tools/private_key.pem），用来给买家「生成解锁码」
  （tools/make_code.py 用）。
- 公钥（PUBLIC_KEY，64 字符 hex）随工具分发，只能「验证」、不能生成签名。
  别人拿到公钥也无法伪造解锁码。
- 私钥绝不能打进工具、不能上传、不能发给任何人。
"""
import os
import sys
import json
import hashlib

# 解锁状态写到「用户可写目录」：.app 内部只读，不能存在包里（否则重装即丢失，
# 且 macOS 上会因签名校验/权限直接写失败）。位置由 paths.py 统一决定。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import paths as _paths
    LICENSE_PATH = os.path.join(_paths.USER_DIR, 'license.json')
except Exception:
    LICENSE_PATH = os.path.join(_HERE, 'license.json')

# —— 免费 / 付费胶片定义（key 与 build_firmware.FILMS 一致）——
FREE_FILMS = ['5207']
PAID_FILMS = ['portra400', 'ektar100', '5219']

# 胶片显示名（用于网页提示）
FILM_DISPLAY = {
    '5207': 'Kodak 5207',
    'portra400': 'Portra 400',
    'ektar100': 'Ektar 100',
    '5219': 'Kodak 5219',
}

# —— 公钥（随工具分发，只能验证、不能生成签名）——
# 64 字符 hex，由 tools/make_license_keys.py 生成。私钥在 Duccio 手里。
PUBLIC_KEY = 'd9f7b582fa1cf28412c6204a0180a31adac6835f0673fccc0a36ed2d3d6c1a0d'

VERSION = '1'

# 惰性加载 cryptography 的 ed25519 公钥对象（避免无谓导入拖慢启动）
_verify_key = None


def _get_verify_key():
    global _verify_key
    if _verify_key is None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        _verify_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY))
    return _verify_key


def _load():
    if not os.path.exists(LICENSE_PATH):
        return {'unlocked': []}
    try:
        d = json.load(open(LICENSE_PATH))
    except Exception:
        return {'unlocked': []}
    d.setdefault('unlocked', [])
    return d


def _save(d):
    os.makedirs(os.path.dirname(LICENSE_PATH), exist_ok=True)
    json.dump(d, open(LICENSE_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def unlocked_films():
    """返回当前已解锁的付费胶片 key 列表（免费款无需解锁）。"""
    d = _load()
    unlocked = [k for k in d.get('unlocked', []) if k in PAID_FILMS]
    return unlocked


def is_unlocked(key):
    # ★ 只有内置付费款需要解锁；用户自建胶片（duccio_xxxx 等自定义 key）
    # 一律放行 —— 之前自建胶片不在名单里被当成「未解锁」，导致导入 CUBE/XMP
    # 建的胶片在生成固件时被 403 拒绝（用户视角就是「导入还要解锁」）。
    if key not in PAID_FILMS:
        return True
    return key in unlocked_films()


def locked_films():
    """返回尚未解锁的付费胶片 key 列表。"""
    unlocked = set(unlocked_films())
    return [k for k in PAID_FILMS if k not in unlocked]


def verify_license_code(code):
    """用 ed25519 公钥校验解锁码，返回 {ok, films, reason}。"""
    if not code or '-' not in code:
        return {'ok': False, 'films': [], 'reason': '格式错误'}
    payload, sig_hex = code.rsplit('-', 1)
    # 解析 payload 先做结构校验（不验签时也能给出清晰报错）
    parts = payload.split(':')
    if len(parts) != 2 or parts[0] != VERSION:
        return {'ok': False, 'films': [], 'reason': '版本不匹配'}
    keys = [k for k in parts[1].split(',') if k in PAID_FILMS]
    if not keys:
        return {'ok': False, 'films': [], 'reason': '无有效胶片'}
    # ed25519 验签
    try:
        sig = bytes.fromhex(sig_hex)
        _get_verify_key().verify(sig, payload.encode())
    except Exception:
        return {'ok': False, 'films': [], 'reason': '签名无效'}
    return {'ok': True, 'films': keys, 'reason': ''}


def apply_license(code):
    """校验并落地解锁码，返回 {ok, unlocked, reason}。

    ★ 商业策略（2026-10-17 定）：不单独解锁 —— 任何一个有效解锁码
    一次性解锁全部三款付费胶片（portra400 / ektar100 / 5219）。
    码里带了哪些 key 无所谓，验签通过就给全家桶。
    """
    r = verify_license_code(code)
    if not r['ok']:
        return {'ok': False, 'unlocked': [], 'reason': r['reason']}
    d = _load()
    cur = set(d.get('unlocked', []))
    cur.update(PAID_FILMS)          # 全家桶：一次解锁全部付费款
    d['unlocked'] = sorted(cur)
    _save(d)
    return {'ok': True, 'unlocked': sorted(cur), 'reason': ''}


def license_status():
    """返回给前端的门控状态：免费/已解锁/锁定。"""
    unlocked = set(unlocked_films())
    status = {}
    for k in FREE_FILMS:
        status[k] = 'free'
    for k in PAID_FILMS:
        status[k] = 'unlocked' if k in unlocked else 'locked'
    return status
