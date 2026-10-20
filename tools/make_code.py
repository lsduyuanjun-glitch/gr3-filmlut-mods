#!/usr/bin/env python3
"""给买家生成解锁码（仅 Duccio 自己用）。

用法：
  python tools/make_code.py portra400            # 解锁单款
  python tools/make_code.py portra400 5219       # 解锁多款
  python tools/make_code.py --all                # 解锁全部付费款

依赖：cryptography（pip install cryptography）
私钥：从环境变量 GR3_LICENSE_SK_FILE 指定的 PEM 文件读取，
      或从 tools/private_key.pem 读取（自己放好，别上传）。
"""
import sys, os, json, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

PAID_FILMS = ['portra400', 'ektar100', '5219']
VERSION = '1'

def _load_sk():
    from cryptography.hazmat.primitives import serialization
    path = os.environ.get('GR3_LICENSE_SK_FILE', os.path.join(HERE, 'private_key.pem'))
    if not os.path.exists(path):
        print(f'找不到私钥文件：{path}')
        print('请先用 make_license_keys.py 生成密钥对，把私钥 PEM 存到 tools/private_key.pem')
        sys.exit(1)
    return serialization.load_pem_private_key(open(path, 'rb').read(), password=None)

def make_code(film_keys):
    sk = _load_sk()
    keys = sorted(set(film_keys) & set(PAID_FILMS))
    if not keys:
        print('没有有效付费胶片。可用的付费款：', PAID_FILMS)
        sys.exit(1)
    payload = VERSION + ':' + ','.join(keys)
    sig = sk.sign(payload.encode()).hex()
    code = payload + '-' + sig
    print('解锁码：')
    print(code)
    print()
    print('胶片：', ', '.join(keys))
    return code

if __name__ == '__main__':
    args = sys.argv[1:]
    if '--all' in args:
        keys = PAID_FILMS
    else:
        keys = [a for a in args if not a.startswith('--')]
    make_code(keys)
