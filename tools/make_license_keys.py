#!/usr/bin/env python3
"""生成 Duccio GR3 工具的非对称签名密钥对（ed25519），并自动配置到位。

用法：
  python tools/make_license_keys.py

产出（自动完成）：
  1. tools/private_key.pem —— 私钥，自己保密保存（绝不上传、不发人）。
  2. webtool/license.py 的 PUBLIC_KEY —— 公钥 hex，随工具分发（只能验证）。

重要：
  - 私钥绝不能打进工具、不能上传 GitHub、不能发给任何人。
  - 公钥可以公开（它只能验证、不能生成签名）。
  - 重复运行会生成新密钥对，之前发出的解锁码会全部失效——所以只跑一次，
    之后把 private_key.pem 备份到安全的地方，别再重跑。
"""
import sys, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print('需要 cryptography 库：pip install cryptography')
    sys.exit(1)

SK_PATH = os.path.join(HERE, 'private_key.pem')
LICENSE_PATH = os.path.join(ROOT, 'webtool', 'license.py')

sk = Ed25519PrivateKey.generate()
pk = sk.public_key()

priv_pem = sk.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
pub_hex = pk.public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
).hex()

# 1) 写私钥
with open(SK_PATH, 'w') as f:
    f.write(priv_pem)
os.chmod(SK_PATH, 0o600)  # 仅本人可读写

# 2) 回写 license.py 的 PUBLIC_KEY
src = open(LICENSE_PATH, encoding='utf-8').read()
new_src, n = re.subn(
    r"PUBLIC_KEY = '[0-9a-fA-F]{64}'",
    f"PUBLIC_KEY = '{pub_hex}'",
    src,
)
if n != 1:
    print('✗ 未能定位 license.py 中的 PUBLIC_KEY，请手动替换为：')
    print(pub_hex)
    sys.exit(1)
open(LICENSE_PATH, 'w', encoding='utf-8').write(new_src)

print('=' * 64)
print('完成。')
print()
print('私钥已写入（请立即备份到安全位置，勿上传）：')
print('  ', SK_PATH)
print()
print('公钥已写入 webtool/license.py 的 PUBLIC_KEY：')
print('  ', pub_hex)
print()
print('提示：私钥生成解锁码（tools/make_code.py），公钥验证。')
print('私钥泄密 = 任何人都能免费解锁。不要再重复运行本脚本。')
print('=' * 64)
