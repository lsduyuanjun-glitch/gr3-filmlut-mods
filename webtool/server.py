#!/usr/bin/env python3
"""GR3 胶片滤镜工具 —— 本地 Web 服务器。

启动后浏览器自动打开 http://localhost:8310 即可使用。
- GET  /           返回网页界面
- GET  /status     返回环境就绪状态
- GET  /*.bin      下载生成的固件
- POST /build      接收 {slot: film} 映射，生成固件

打包版要点：所有耗时操作都在**本进程内**执行（PyInstaller 下没有可独立调用的
Python 解释器，subprocess 起子进程等于重复启动整个 app）。
数据分两层：只读资源在 app 包内，可写数据（胶片库/解锁/输出）在用户目录。
"""
import os
import sys
import json
import base64
import threading
import webbrowser
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# —— 统一路径解析（同目录的 paths.py）——
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import paths  # noqa: E402

RESOURCE = paths.RESOURCE_DIR
USER_DIR = paths.USER_DIR
paths.ensure_user_dirs()          # 建好可写目录 + 首次运行播种胶片库
sys.path.insert(0, RESOURCE)      # 引擎 .py 在资源目录

# 临时文件：不用 stdlib tempfile —— 它在「禁止删除文件」的受限环境下会整体失效。
# gr3_tmp 改为在用户数据目录下自建 scratch 区，打包版更健壮。
import gr3_tmp  # noqa: E402
gr3_tmp.patch_tempfile()   # 顺手给 stdlib tempfile 兜底（第三方库可能仍会用它）

try:
    import license as _lic
except ImportError:
    _lic = None

# ★ 引擎模块在**启动时**就导入（顶层），而不是等请求来了才 import。
# 之前是请求内 import：如果打包布局有问题（如 sys.path 缺资源根），要等用户
# 点「XMP 直读」才炸出 No module named 'film_pipeline'，非常隐蔽。
# 顶层导入让问题在启动瞬间暴露（服务起不来），e2e 测试也能第一时间拦住。
import film_pipeline as fp  # noqa: E402

PORT = int(os.environ.get('GR3_PORT', '8310'))
FW = paths.find_firmware()
HTML_PATH = paths.RES_INDEX_HTML
OUT_NAME = 'gr3_film_mods_custom.bin'
OUT_PATH = os.path.join(paths.OUTPUT_DIR, OUT_NAME)
CUBE_DIR = paths.CUBE_DIR

# ★ 版本号：启动时探测「占用端口的旧进程」是否同版本；不同版本（旧 App 还在跑）就自动
#   kill 它再接管端口。否则用户解压新 App 双击，新进程会因端口被旧进程占用而「复用旧实例」，
#   浏览器永远显示旧界面（用户反复遇到的「和之前没区别」）。
APP_VERSION = '1.5.2'


def _open_browser():
    """启动后自动用系统默认浏览器打开界面（原生 .app 无终端，靠这个给用户反馈）。

    ★ URL 带时间戳查询参数：如果浏览器里还开着上一会话的 localhost:8310 标签，
      带「新 URL」的打开会强制导航/新开标签重新加载页面——否则浏览器只聚焦旧标签，
      旧 JS 继续跑（内存里还留着已删胶片的下拉项、旧版界面逻辑），用户会看到
      「删了还在、新建不显示」的假象（实际服务端都是对的）。
    """
    import time as _t
    url = f'http://localhost:{PORT}/?t={int(_t.time())}'

    def _open():
        import time
        time.sleep(1.2)  # 等服务器起来
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def _is_ascii_name(s):
    """胶片名字/短码只允许 ASCII 可打印字符（机内图标字体 + 字符串表安全）。"""
    return bool(s) and all(0x20 <= ord(c) <= 0x7e for c in s)


def _crop_square(im):
    """把 PIL 图片等比缩放 + 居中裁剪成正方形（自定义图标用）。"""
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.wfile.write(body)

    def _send_file(self, fpath, ctype='application/octet-stream', download=True):
        if not os.path.exists(fpath):
            self._send(404, json.dumps({'error': '文件不存在'}))
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        if download:
            self.send_header('Content-Disposition',
                             f'attachment; filename="{os.path.basename(fpath)}"')
        self.send_header('Content-Length', str(os.path.getsize(fpath)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        with open(fpath, 'rb') as f:
            self.wfile.write(f.read())

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            if os.path.exists(HTML_PATH):
                self._send(200, open(HTML_PATH, encoding='utf-8').read(), 'text/html')
            else:
                self._send(404, '<h1>index.html 未找到</h1>', 'text/html')
        elif path == '/status':
            import models as _models
            fw_models = {m[0]: os.path.exists(paths.find_firmware(m[0])) for m in _models.list_models()}
            self._send(200, json.dumps({
                'version': APP_VERSION,
                'fw_ready': os.path.exists(FW),
                'fw_path': FW,
                'models': _models.list_models(),
                'fw_by_model': fw_models,
                'user_dir': USER_DIR,
                'outputs': [OUT_NAME],
            }))
        elif path == '/film/list':
            # 前端 loadLibrary() 用 GET 请求（此前误放 do_POST，导致自建胶片加载不出来）
            self._handle_film_list()
        elif path == '/license/status':
            self._handle_license_status()
        elif path.endswith('.bin'):
            rel = path.lstrip('/')
            if rel.startswith('official_firmware/'):
                self._send_file(os.path.join(RESOURCE, rel))
            else:
                self._send_file(os.path.join(paths.OUTPUT_DIR, os.path.basename(path)))
        elif path.endswith('_icons.png'):
            self._send_file(os.path.join(paths.OUTPUT_DIR, os.path.basename(path)),
                            'image/png', download=False)
        elif path.endswith('.png') or path.endswith('.cube'):
            ctype = 'image/png' if path.endswith('.png') else 'application/octet-stream'
            self._send_file(os.path.join(paths.OUTPUT_DIR, os.path.basename(path)), ctype)
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
        elif path == '/film/icon':
            self._handle_film_icon(data)
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

    def _box_spec(self, data, name, short):
        body = data.get('body', [16, 34, 68])
        strip = data.get('strip', [227, 30, 36])
        brand_c = (255, 255, 255) if data.get('brand_col', 'white') == 'white' else (0, 0, 0)
        name_c = (255, 255, 255) if data.get('name_col', 'white') == 'white' else (0, 0, 0)
        speed_c = (255, 255, 255) if data.get('speed_col', 'white') == 'white' else (0, 0, 0)
        box_name = data.get('box_name', name)
        speed = short or name
        return (list(body), list(strip), brand_c, box_name, name_c, speed, speed_c)

    def _handle_film_create_from_xmp(self, data):
        """上传 .xmp 预设（base64）+ 名字 -> 解析 crs:Look -> cube -> 拟合 -> 进库。全自动。"""
        import hashlib as _hl
        b64 = data.get('xmp', '')
        name = data.get('name', '')
        short = data.get('short', '')
        if not b64 or not name:
            self._send(400, json.dumps({'error': '缺少 XMP 或名字'}))
            return
        if not _is_ascii_name(name) or (short and not _is_ascii_name(short)):
            self._send(400, json.dumps({'error': '胶片名字/短码仅支持英文、数字及常用符号（不支持中文）'}))
            return
        tmp_name = gr3_tmp.write_bytes(base64.b64decode(b64), '.xmp')
        key = 'duccio_' + _hl.md5(name.encode()).hexdigest()[:8]
        box_spec = self._box_spec(data, name, short)
        try:
            result = fp.run_film_from_xmp(tmp_name, key, name, box_spec, CUBE_DIR)
        except Exception as e:
            self._send(500, json.dumps({'error': 'XMP 解析/拟合失败', 'stderr': str(e)[-2000:]}))
            return
        finally:
            gr3_tmp.cleanup(tmp_name)
        saved = self._save_film_to_library(result, name, short)
        if saved.get('_lib_err'):
            self._send(500, json.dumps({'error': '拟合成功但入库失败', 'stderr': saved['_lib_err']}))
            return
        self._send(200, json.dumps({'ok': True, 'film': saved, 'de': result.get('de'),
                                    'xmp': result.get('xmp')}))

    def _handle_film_create_from_cube(self, data):
        """上传 .cube（base64）+ 名字 -> 直接拟合进库。跳过 HALD 转 cube。"""
        import hashlib as _hl
        b64 = data.get('cube', '')
        name = data.get('name', '')
        short = data.get('short', '')
        if not b64 or not name:
            self._send(400, json.dumps({'error': '缺少 cube 或名字'}))
            return
        if not _is_ascii_name(name) or (short and not _is_ascii_name(short)):
            self._send(400, json.dumps({'error': '胶片名字/短码仅支持英文、数字及常用符号（不支持中文）'}))
            return
        tmp_name = gr3_tmp.write_bytes(base64.b64decode(b64), '.cube')
        key = 'duccio_' + _hl.md5(name.encode()).hexdigest()[:8]
        box_spec = self._box_spec(data, name, short)
        try:
            result = fp.run_film_from_cube(tmp_name, key, name, box_spec, CUBE_DIR)
        except Exception as e:
            self._send(500, json.dumps({'error': 'cube 拟合失败', 'stderr': str(e)[-2000:]}))
            return
        finally:
            gr3_tmp.cleanup(tmp_name)
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

    def _handle_film_icon(self, data):
        """设置自建胶片的机内图标：接收图片(base64) + key，等比缩放+居中裁剪成 40×40，
        存成 PNG base64 写进胶片库的 icon 字段。"""
        import base64 as _b64
        import io as _io
        key = data.get('key', '')
        b64 = data.get('image', '')
        if not key or not b64:
            self._send(400, json.dumps({'error': '缺少 key 或图片'}))
            return
        try:
            from PIL import Image as _Image
            raw = _b64.b64decode(b64)
            im = _Image.open(_io.BytesIO(raw)).convert('RGBA')
            # 等比缩放 + 居中裁剪成 40×40
            im = _crop_square(im).resize((40, 40), _Image.LANCZOS)
            buf = _io.BytesIO()
            im.save(buf, 'PNG')
            png_b64 = _b64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            self._send(400, json.dumps({'error': '图片解析失败（需 PNG/JPG）', 'stderr': str(e)[-200:]}))
            return
        try:
            import film_library as fl
            ok = fl.set_film_icon(key, png_b64)
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
        # 机型：默认 GR III；未支持机型直接拒绝（绝不静默产出错误固件）
        import models
        model = data.get('model') or 'gr3'
        spec = models.get_model(model)
        if not spec.supported:
            self._send(400, json.dumps({
                'error': f'机型「{spec.display_name}」尚未开放',
                'hint': spec.note or '该机型待逆向，暂不可用',
                'model': spec.id,
            }))
            return

        # 按机型定位官方固件（SHA 识别）
        fw_path = paths.find_firmware(model)
        if not os.path.exists(fw_path):
            self._send(400, json.dumps({
                'error': f'找不到 {spec.display_name}（{spec.official_firmware_version}）官方固件',
                'hint': f'请把对应机型的官方固件放到：{paths.USER_FW_DIR}',
                'fw_path': fw_path,
            }))
            return

        films_order = data.get('films')
        if not (isinstance(films_order, list) and films_order):
            films_order = ['5207']

        # 颗粒（逐槽位）：grains = list[int]，长度对齐 films_order；0=Off 1=High 2=Mid 3=Low
        grains = data.get('grains')
        if isinstance(grains, list):
            try:
                grains = [max(0, min(3, int(g) if g is not None else 2)) for g in grains]
            except (TypeError, ValueError):
                grains = None
        else:
            grains = None

        # 颗粒模式（兼容旧单值）：grain_fixed = None→可调(机内菜单) / 0→无颗粒 / 1/2/3→固件写死
        grain_fixed = data.get('grain_fixed')
        if grain_fixed is not None:
            try:
                grain_fixed = int(grain_fixed)
                if grain_fixed not in (0, 1, 2, 3):
                    grain_fixed = None
            except (TypeError, ValueError):
                grain_fixed = None

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
            if grains is not None:
                # 对齐长度：补齐/截断到 len(films_order)
                grains = (grains + [2] * len(films_order))[:len(films_order)]
                result = bf.build(fw_path, OUT_PATH, films_order=films_order, grains=grains, model=model)
            elif grain_fixed is not None and grain_fixed > 0:
                # 固件写死颗粒（1=High 2=Mid 3=Low）
                result = bf.build(fw_path, OUT_PATH, films_order=films_order, grain_fixed=grain_fixed, model=model)
            elif grain_fixed == 0:
                # 无颗粒
                result = bf.build(fw_path, OUT_PATH, films_order=films_order, model=model)
            else:
                # 可调颗粒（机内菜单）
                result = bf.build(fw_path, OUT_PATH, films_order=films_order, grain_native=True, model=model)
        except Exception as e:
            self._send(500, json.dumps({'error': '生成失败', 'stderr': str(e)[-2000:]}))
            return

        # 构建成功后自动核验（进程内；核验失败不影响产出，只影响「可下载」状态）
        try:
            verify = self._verify_firmware(OUT_PATH, films_order)
        except Exception as e:
            verify = {'ok': False, 'detail': f'核验异常：{str(e)[-200:]}'}
        result['verify'] = verify

        self._send(200, json.dumps(result))

    def _verify_firmware(self, out_path, films_order=None):
        """自动核验 v16 固件完整性，返回 {ok, detail}。进程内执行 verify_slots16。"""
        import io
        import contextlib
        import runpy
        import json as _j

        fits_dir = paths.RES_FITS_V16
        film_order = films_order or ['portra400', 'ektar100', '5207', '5219']

        lib = {}
        lib_path = paths.LIB_PATH
        if os.path.exists(lib_path):
            try:
                lib = _j.load(open(lib_path, encoding='utf-8')).get('films', {})
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
                    fp2 = entry['fit'] if os.path.isabs(entry['fit']) else os.path.join(RESOURCE, entry['fit'])
                    if os.path.exists(fp2):
                        d = _j.load(open(fp2, encoding='utf-8'))
                        if not d.get('hue_q10'):
                            d['hue_q10'] = [[[1024, 0, 0], [0, 1024, 0], [0, 0, 1024]] for _ in range(12)]
                            fp2 = gr3_tmp.write_text(_j.dumps(d, ensure_ascii=False), '.json')
                            tmp_files.append(fp2)
                        fp = fp2
                    else:
                        return {'ok': False, 'detail': f'找不到 fit {key}'}
                else:
                    return {'ok': False, 'detail': f'找不到 fit {key}.json'}
            args.append(f'{key}={fp}')

        verify_py = os.path.join(RESOURCE, 'verify_slots16.py')
        old_argv, old_cwd = sys.argv, os.getcwd()
        buf = io.StringIO()
        try:
            sys.argv = [verify_py, FW, out_path] + args
            os.chdir(RESOURCE)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                runpy.run_path(verify_py, run_name='__main__')
        except SystemExit:
            pass
        except Exception as e:
            return {'ok': False, 'detail': f'核验异常 {str(e)[-200:]}'}
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)
            for tf in tmp_files:
                gr3_tmp.cleanup(tf)

        out = buf.getvalue()
        ok = 'ALL OK' in out
        detail = 'ALL OK' if ok else ('SOME FAILED' if 'SOME FAILED' in out else '无法判定')
        return {'ok': ok, 'detail': detail}


def _port_owner_pid():
    """返回占用 PORT 的进程 PID（找不到返回 None）。"""
    import glob
    try:
        with open('/proc/net/tcp') as _:
            pass  # linux 分支（本工具 macOS 专用，走不到）
    except Exception:
        pass
    # macOS：lsof 找监听端口的进程
    try:
        out = subprocess.run(
            ['lsof', '-ti', f'tcp:{PORT}', '-sTCP:LISTEN'],
            capture_output=True, text=True, timeout=5).stdout.strip()
        return int(out.splitlines()[0]) if out else None
    except Exception:
        return None


def _probe_self(path):
    """探测占用 PORT 的进程是否是一个健康的「本工具」实例（返回 True/False）。

    用 http.client（而非 urllib.request）——http.client 是更底层的模块，
    依赖更少，避免「打包版 stdlib 缺 urllib/request.py」这类问题直接崩溃。
    """
    try:
        import http.client as _hc
        c = _hc.HTTPConnection('127.0.0.1', PORT, timeout=3)
        c.request('GET', path)
        r = c.getresponse()
        body = r.read(4096)
        c.close()
        return r.status == 200 and b'<!DOCTYPE' in body
    except Exception:
        return False


def _probe_version():
    """探测占用 PORT 的进程的版本号（通过 /status）；不是本工具或探测失败返回 None。"""
    try:
        import http.client as _hc
        import json as _j
        c = _hc.HTTPConnection('127.0.0.1', PORT, timeout=3)
        c.request('GET', '/status')
        r = c.getresponse()
        body = r.read(4096)
        c.close()
        if r.status != 200:
            return None
        return _j.loads(body.decode('utf-8', 'ignore')).get('version')
    except Exception:
        return None


def main():
    # 端口占用时的处理（自动、不弹窗、不要求用户手动杀进程）：
    # ① 健康实例（/ 返回正常页面）→ 直接开浏览器，复用已有实例；
    # ② 失效旧进程（用户把旧 app 丢进废纸篓/删除，但进程没退，/ 返回 404）→
    #    自动 kill 它，稍等重试绑定，随后正常启动接管端口。
    #    —— 之前版本在这里弹窗让用户去活动监视器手动杀进程，对用户太不友好，
    #      反而成了「程序打不开」的元凶，已改为自动清理。
    for _attempt in range(2):
        try:
            server = HTTPServer(('127.0.0.1', PORT), Handler)
            break
        except OSError:
            _ver = _probe_version()
            if _ver == APP_VERSION:
                # 同版本健康实例 → 复用（用户只是重复双击同一个版本）
                print(f'本工具已在运行（端口 {PORT}），直接打开浏览器窗口。')
                _open_browser()
                import time
                time.sleep(3)
                return
            # 不同版本 / 失效旧进程 → 自动终止后重试，接管端口
            pid = _port_owner_pid()
            print(f'检测到旧版本实例（版本 {_ver or "?"}）占用端口 {PORT}，自动清理升级（PID {pid or "?"}）…')
            if pid:
                try:
                    subprocess.run(['kill', str(pid)], timeout=5)
                except Exception:
                    pass
            import time
            time.sleep(1)
    else:
        print(f'端口 {PORT} 清理后仍被占用，请重启电脑后重试。')
        import time
        time.sleep(3)
        return
    _open_browser()
    print(f'GR3 胶片滤镜工具已启动: http://localhost:{PORT}')
    print(f'用户数据目录: {USER_DIR}')
    print(f'官方固件: {FW}（{"已就绪" if os.path.exists(FW) else "未找到"}）')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
