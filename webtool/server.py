#!/usr/bin/env python3
"""GR3 胶片滤镜工具 —— 本地 Web 服务器。

启动后浏览器打开 http://localhost:8310 即可使用。
- GET  /           返回网页界面
- GET  /status     返回环境就绪状态
- GET  /*.bin      下载生成的固件
- POST /build      接收 {slot: film} 映射，调用 build_firmware.py 生成固件
"""
import os, sys, json, subprocess, base64, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# —— PyInstaller 打包运行时目录解析 ——
# onedir 模式下，数据文件解到 sys.executable 同级的 _internal/ 目录；
# onefile 模式下解到 sys._MEIPASS。这里统一取「能定位到引擎代码的根目录」。
def _bundle_root():
    if getattr(sys, 'frozen', False):
        # 打包环境：优先 _MEIPASS（onefile 解压目录），否则 executable 所在目录
        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(sys.executable)
        # PyInstaller 5+ 把 datas 放进 _internal
        internal = os.path.join(os.path.dirname(sys.executable), '_internal')
        for cand in (base, internal):
            if os.path.exists(os.path.join(cand, 'make_slots15.py')):
                return cand
        return base
    return None

_BUNDLE = _bundle_root()

TOOL_DIR = _BUNDLE or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOL_DIR)
try:
    import license as _lic
except ImportError:
    _lic = None

# —— 可移植路径解析 ——
# 引擎代码（gr3-film-mods 的 make_slots15/16、make_grain_native、gr3patch 等）放在本目录下的 engine/。
# 打包时把 gr3-film-mods 整个拷到 engine/ 即可，工具目录可整体移动、跨机器运行。
def _resolve_repo():
    # 0) 打包环境：引擎 .py 平铺在 TOOL_DIR（_internal）根目录
    if getattr(sys, 'frozen', False):
        if os.path.exists(os.path.join(TOOL_DIR, 'make_slots15.py')):
            return TOOL_DIR
    # 1) 环境变量显式指定（调试/自定义用）
    if os.environ.get('GR3_REPO'):
        return os.environ['GR3_REPO']
    # 2) 打包结构：本目录下的 engine/ 子目录
    bundled = os.path.join(TOOL_DIR, 'engine')
    if os.path.isdir(bundled) and os.path.exists(os.path.join(bundled, 'make_slots15.py')):
        return bundled
    # 3) 仓库结构：引擎代码在 webtool/ 的上一级目录（仓库根，如 gr3-filmlut-mods/）
    #    直接回溯向上找含 make_slots15.py 的目录，不依赖仓库具体名字
    for up in range(1, 5):
        cand = os.path.abspath(os.path.join(TOOL_DIR, *(['..'] * up)))
        if os.path.isdir(cand) and os.path.exists(os.path.join(cand, 'make_slots15.py')):
            return cand
    # 4) 兼容旧名 gr3-film-mods（历史开发结构）
    for up in (3, 4, 2):
        dev = os.path.abspath(os.path.join(TOOL_DIR, *(['..'] * up), 'gr3-film-mods'))
        if os.path.isdir(dev) and os.path.exists(os.path.join(dev, 'make_slots15.py')):
            return dev
    return bundled  # 兜底：即便不存在也返回 bundled，让后续 os.path.exists 判定给出清晰报错

REPO = _resolve_repo()

# 官方固件：默认放在本目录 official_firmware/ 下（不随包分发，用户自行下载放入）。
# 文件名优先匹配 fwdc239b（GR III 2.10）。可用环境变量 GR3_FW 覆盖。
def _resolve_fw():
    if os.environ.get('GR3_FW'):
        return os.environ['GR3_FW']
    d = os.path.join(TOOL_DIR, 'official_firmware')
    if os.path.isdir(d):
        for fn in ('fwdc239b.bin', 'fwdc239b_GR3_2.10_official.bin'):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                return p
        # 兜底：目录里任意 .bin（排除 GR4 固件）
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith('.bin') and 'GR4' not in fn and '248' not in fn:
                return os.path.join(d, fn)
    return os.path.join(d, 'fwdc239b.bin')  # 缺省值，供 /status 报「未就绪」

FW = _resolve_fw()

# Python 解释器：优先用本包自带（打包版），否则退回当前解释器 / 显式环境变量。
def _resolve_python():
    if os.environ.get('GR3_PY'):
        return os.environ['GR3_PY']
    bundled = os.path.join(TOOL_DIR, 'runtime', 'bin', 'python3')
    if os.path.exists(bundled):
        return bundled
    return sys.executable  # 开发环境：当前正在运行的 Python

VENV_PY = _resolve_python()

PORT = 8310
XMP2CUBE = os.path.join(REPO, 'xmp2cube.py')
FILM_PIPELINE = os.path.join(REPO, 'film_pipeline.py')
CUBE_DIR = os.path.join(REPO, 'work', 'films_v11', 'cubes')

HTML_PATH = os.path.join(TOOL_DIR, 'index.html')


def _is_ascii_name(s):
    """胶片名字/短码只允许 ASCII 可打印字符（机内图标字体 + 字符串表安全）。"""
    return bool(s) and all(0x20 <= ord(c) <= 0x7e for c in s)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            if os.path.exists(HTML_PATH):
                self._send(200, open(HTML_PATH, encoding='utf-8').read(), 'text/html')
            else:
                self._send(404, '<h1>index.html 未找到</h1>', 'text/html')
        elif path == '/status':
            self._send(200, json.dumps({
                'fw_ready': os.path.exists(FW),
                'repo_ready': os.path.exists(os.path.join(REPO, 'make_films10.py')),
                'venv_ready': os.path.exists(VENV_PY),
            }))
        elif path == '/film/list':
            # 前端 loadLibrary() 用 GET 请求，必须放在 do_GET（此前误放 do_POST，导致自建胶片永远加载不出来）
            self._handle_film_list()
        elif path == '/license/status':
            self._handle_license_status()
        elif path.endswith('.bin'):
            # 支持 official_firmware/ 子目录里的官方固件下载
            rel = path.lstrip('/')
            fpath = os.path.join(TOOL_DIR, rel) if rel.startswith('official_firmware/') else os.path.join(TOOL_DIR, os.path.basename(path))
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(fpath)}"')
                self.send_header('Content-Length', str(os.path.getsize(fpath)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self._send(404, json.dumps({'error': '固件不存在，请先生成'}))
        elif path.endswith('_icons.png'):
            fpath = os.path.join(TOOL_DIR, os.path.basename(path))
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self._send(404, json.dumps({'error': 'not found'}))
        elif path.endswith('.png') or path.endswith('.cube'):
            # 下载 HALD 身份图 / 生成的 cube
            fpath = os.path.join(TOOL_DIR, os.path.basename(path))
            if os.path.exists(fpath):
                ctype = 'image/png' if path.endswith('.png') else 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(fpath)}"')
                self.send_header('Content-Length', str(os.path.getsize(fpath)))
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self._send(404, json.dumps({'error': 'not found'}))
        else:
            self._send(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b'{}'
        try:
            data = json.loads(body) if body else {}
        except Exception:
            self._send(400, json.dumps({'error': '无效 JSON'}))
            return

        if path == '/build':
            self._handle_build(data)
        elif path == '/film/list':
            self._handle_film_list()
        elif path == '/film/create_from_xmp':
            self._handle_film_create_from_xmp(data)
        elif path == '/film/create_from_cube':
            self._handle_film_create_from_cube(data)
        elif path == '/film/rename':
            self._handle_film_rename(data)
        elif path == '/film/delete':
            self._handle_film_delete(data)
        elif path == '/license/apply':
            self._handle_license_apply(data)
        else:
            self._send(404, json.dumps({'error': 'not found'}))

    def _handle_film_list(self):
        try:
            import film_library as fl
            films = fl.list_films()
        except Exception:
            films = []
        self._send(200, json.dumps({'ok': True, 'films': films}))

    def _save_film_to_library(self, result, name, short):
        """把 run_film 的结果写入胶片库，返回保存后的胶片。"""
        try:
            import film_library as fl
            return fl.add_film(result, nick=name, short=(short or name))
        except Exception as e:
            result['_lib_err'] = str(e)[-500:]
            return result

    def _handle_film_create_from_xmp(self, data):
        """上传 .xmp 预设（base64）+ 名字 -> 自动解析 crs:Look -> cube -> 拟合 -> 进库。全自动。"""
        b64 = data.get('xmp', '')
        name = data.get('name', '')
        short = data.get('short', '')
        if not b64 or not name:
            self._send(400, json.dumps({'error': '缺少 XMP 或名字'}))
            return
        if not _is_ascii_name(name) or (short and not _is_ascii_name(short)):
            self._send(400, json.dumps({'error': '胶片名字/短码仅支持英文、数字及常用符号（不支持中文）'}))
            return
        tmp = tempfile.NamedTemporaryFile(suffix='.xmp', delete=False)
        tmp.write(base64.b64decode(b64))
        tmp.close()

        body = data.get('body', [16, 34, 68])
        strip = data.get('strip', [227, 30, 36])
        brand_c = (255, 255, 255) if data.get('brand_col', 'white') == 'white' else (0, 0, 0)
        name_c = (255, 255, 255) if data.get('name_col', 'white') == 'white' else (0, 0, 0)
        speed_c = (255, 255, 255) if data.get('speed_col', 'white') == 'white' else (0, 0, 0)
        box_name = data.get('box_name', name)
        speed = short or name
        import hashlib as _hl
        key = 'duccio_' + _hl.md5(name.encode()).hexdigest()[:8]

        box_spec = (list(body), list(strip), brand_c, box_name, name_c, speed, speed_c)

        try:
            import film_pipeline as fp
            result = fp.run_film_from_xmp(tmp.name, key, name, box_spec, CUBE_DIR)
        except Exception as e:
            self._send(500, json.dumps({'error': 'XMP 解析/拟合失败', 'stderr': str(e)[-2000:]}))
            return
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        saved = self._save_film_to_library(result, name, short)
        if saved.get('_lib_err'):
            self._send(500, json.dumps({'error': '拟合成功但入库失败', 'stderr': saved['_lib_err']}))
            return
        self._send(200, json.dumps({'ok': True, 'film': saved, 'de': result.get('de'),
                                    'xmp': result.get('xmp')}))

    def _handle_film_create_from_cube(self, data):
        """上传 .cube（base64）+ 名字 -> 直接拟合进库。跳过 HALD 转 cube。"""
        b64 = data.get('cube', '')
        name = data.get('name', '')
        short = data.get('short', '')
        if not b64 or not name:
            self._send(400, json.dumps({'error': '缺少 cube 或名字'}))
            return
        if not _is_ascii_name(name) or (short and not _is_ascii_name(short)):
            self._send(400, json.dumps({'error': '胶片名字/短码仅支持英文、数字及常用符号（不支持中文）'}))
            return
        tmp = tempfile.NamedTemporaryFile(suffix='.cube', delete=False)
        tmp.write(base64.b64decode(b64))
        tmp.close()

        body = data.get('body', [16, 34, 68])
        strip = data.get('strip', [227, 30, 36])
        brand_c = (255, 255, 255) if data.get('brand_col', 'white') == 'white' else (0, 0, 0)
        name_c = (255, 255, 255) if data.get('name_col', 'white') == 'white' else (0, 0, 0)
        speed_c = (255, 255, 255) if data.get('speed_col', 'white') == 'white' else (0, 0, 0)
        box_name = data.get('box_name', name)
        speed = short or name
        import hashlib as _hl
        key = 'duccio_' + _hl.md5(name.encode()).hexdigest()[:8]

        box_spec = (list(body), list(strip), brand_c, box_name, name_c, speed, speed_c)

        try:
            import film_pipeline as fp
            result = fp.run_film_from_cube(tmp.name, key, name, box_spec, CUBE_DIR)
        except Exception as e:
            self._send(500, json.dumps({'error': 'cube 拟合失败', 'stderr': str(e)[-2000:]}))
            return
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        saved = self._save_film_to_library(result, name, short)
        if saved.get('_lib_err'):
            self._send(500, json.dumps({'error': '拟合成功但入库失败', 'stderr': saved['_lib_err']}))
            return
        self._send(200, json.dumps({'ok': True, 'film': saved, 'de': result.get('de')}))

    def _handle_film_rename(self, data):
        key = data.get('key', '')
        name = data.get('name', '')
        nick = data.get('nick')
        short = data.get('short')
        if not key or not name:
            self._send(400, json.dumps({'error': '缺少 key 或名字'}))
            return
        try:
            import film_library as fl
            film = fl.rename_film(key, name, nick, short)
        except Exception:
            film = None
        self._send(200, json.dumps({'ok': film is not None, 'film': film}))

    def _handle_film_delete(self, data):
        key = data.get('key', '')
        if not key:
            self._send(400, json.dumps({'error': '缺少 key'}))
            return
        try:
            import film_library as fl
            ok = fl.delete_film(key)
        except Exception:
            ok = False
        self._send(200, json.dumps({'ok': ok}))

    def _handle_license_status(self):
        """返回各胶片的解锁状态：free / unlocked / locked。"""
        if _lic is None:
            self._send(200, json.dumps({'ok': True, 'status': {}, 'films': {
                'free': ['5207'], 'paid': ['portra400', 'ektar100', '5219']}}))
            return
        self._send(200, json.dumps({
            'ok': True,
            'status': _lic.license_status(),
            'films': {'free': _lic.FREE_FILMS, 'paid': _lic.PAID_FILMS},
            'display': _lic.FILM_DISPLAY,
        }))

    def _handle_license_apply(self, data):
        """校验并落地解锁码。"""
        code = (data.get('code') or '').strip()
        if not code:
            self._send(400, json.dumps({'error': '缺少解锁码'}))
            return
        if _lic is None:
            self._send(500, json.dumps({'error': 'license 模块未加载'}))
            return
        r = _lic.apply_license(code)
        self._send(200, json.dumps(r))

    def _handle_build(self, data):
        if not os.path.exists(FW):
            self._send(400, json.dumps({'error': f'找不到官方固件 {FW}'}))
            return

        out_name = data.get('out_name', 'gr3_film_mods_custom.bin')
        out_path = os.path.join(TOOL_DIR, out_name)

        films_order = data.get('films')
        if not (isinstance(films_order, list) and films_order):
            films_order = ['5207']

        # 门控：付费胶片必须已解锁，否则拒绝构建（免费款 5207 始终放行）
        if _lic is not None:
            locked = [k for k in films_order if not _lic.is_unlocked(k)]
            if locked:
                names = ', '.join(_lic.FILM_DISPLAY.get(k, k) for k in locked)
                self._send(403, json.dumps({
                    'error': f'以下胶片未解锁：{names}',
                    'locked': locked,
                }))
                return

        # 进程内构建（PyInstaller 打包后无独立 Python 子进程可用）
        try:
            import build_firmware as bf
            result = bf.build(FW, out_path, films_order=films_order, grain_native=True)
        except Exception as e:
            self._send(500, json.dumps({'error': '生成失败', 'stderr': str(e)[-2000:]}))
            return

        # 构建成功后自动核验（尽力而为：verify 依赖脚本式 verify_slots16，失败不影响产出）
        try:
            verify = self._verify_firmware(out_path, films_order)
        except Exception:
            verify = {'ok': False, 'detail': '核验跳过（打包环境）'}
        result['verify'] = verify

        self._send(200, json.dumps(result))

    def _verify_firmware(self, out_path, films_order=None):
        """自动核验 v16 固件完整性，返回 {ok, detail}。"""
        # 胶片 fit：v16 fits 目录优先，自建胶片从胶片库取，顺序与构建一致
        fits_dir = os.path.join(REPO, 'work', 'films_v16', 'fits', 'duccio')
        film_order = films_order or ['portra400', 'ektar100', '5207', '5219']

        lib = {}
        lib_path = os.path.join(REPO, 'film_library.json')
        if os.path.exists(lib_path):
            try:
                lib = json.load(open(lib_path)).get('films', {})
            except Exception:
                lib = {}

        args = []
        tmp_files = []
        for key in film_order:
            fp = os.path.join(fits_dir, f'{key}.json')
            if not os.path.exists(fp):
                entry = lib.get(key)
                if entry and entry.get('fit'):
                    # 自建胶片 fit：新建链路已注入 hue_q10；旧 v11 fit 缺它时按 build 同款规则注入中性矩阵
                    fp2 = os.path.join(REPO, entry['fit'])
                    if os.path.exists(fp2):
                        import json as _j
                        d = _j.load(open(fp2))
                        if not d.get('hue_q10'):
                            d['hue_q10'] = [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)]
                            import tempfile as _tf
                            tf = _tf.NamedTemporaryFile(mode='w', suffix='.json', delete=False, dir=tempfile.gettempdir())
                            _j.dump(d, tf, ensure_ascii=False); tf.close()
                            fp2 = tf.name; tmp_files.append(tf.name)
                        fp = fp2
                    else:
                        return {'ok': False, 'detail': f'找不到 fit {key}'}
                else:
                    return {'ok': False, 'detail': f'找不到 fit {key}.json'}
            args.append(f'{key}={fp}')

        verify_py = os.path.join(REPO, 'verify_slots16.py')
        cmd = [VENV_PY, verify_py, FW, out_path] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=REPO)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'detail': '核验超时'}
        except Exception as e:
            return {'ok': False, 'detail': f'核验异常 {e}'}
        finally:
            for tf in tmp_files:
                try:
                    os.unlink(tf)
                except Exception:
                    pass

        out = (r.stdout or '') + (r.stderr or '')
        ok = 'ALL OK' in out
        detail = 'ALL OK' if ok else ('SOME FAILED' if 'SOME FAILED' in out else '无法判定')
        return {'ok': ok, 'detail': detail}

def _open_browser():
    """启动后自动用系统默认浏览器打开界面（原生 .app 无终端，靠这个给用户反馈）。"""
    import threading, time
    url = f'http://localhost:{PORT}'
    def _open():
        time.sleep(1.2)  # 等服务器起来
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def main():
    # 端口占用时先清理（可能上次未正常退出残留的进程）
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', PORT)); s.close()
    except OSError:
        # 端口被占：尝试通知已有实例，直接复用（不做破坏性 kill，避免误杀）
        pass
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    _open_browser()
    print(f'GR3 胶片滤镜工具已启动: http://localhost:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')

if __name__ == '__main__':
    main()
