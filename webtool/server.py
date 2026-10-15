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

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))

# —— 可移植路径解析 ——
# 引擎代码（gr3-film-mods 的 make_slots15/16、make_grain_native、gr3patch 等）放在本目录下的 engine/。
# 打包时把 gr3-film-mods 整个拷到 engine/ 即可，工具目录可整体移动、跨机器运行。
def _resolve_repo():
    # 1) 环境变量显式指定（调试/自定义用）
    if os.environ.get('GR3_REPO'):
        return os.environ['GR3_REPO']
    # 2) 打包结构：本目录下的 engine/ 子目录
    bundled = os.path.join(TOOL_DIR, 'engine')
    if os.path.isdir(bundled) and os.path.exists(os.path.join(bundled, 'make_slots15.py')):
        return bundled
    # 3) 开发结构：仓库内的 gr3-film-mods（仓库内开发时）
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
        else:
            self._send(404, json.dumps({'error': 'not found'}))

    def _handle_film_list(self):
        r = subprocess.run([VENV_PY, '-c',
            f"import sys; sys.path.insert(0,'{TOOL_DIR}'); import film_library as fl; "
            f"import json; print(json.dumps(fl.list_films(), ensure_ascii=False))"],
            capture_output=True, text=True, timeout=15, cwd=TOOL_DIR)
        try:
            films = json.loads(r.stdout.strip())
        except Exception:
            films = []
        self._send(200, json.dumps({'ok': True, 'films': films}))

    def _save_film_to_library(self, result, name, short):
        """把 run_film 的结果写入胶片库，返回保存后的胶片。"""
        # 注意：result 必须以「JSON 字符串字面量」嵌入 -c 代码，
        # 直接嵌 dict 文本会让 json.loads 收到 dict 而报 TypeError（此前入库静默失败的根因）
        payload = json.dumps(json.dumps(result, ensure_ascii=False))
        r2 = subprocess.run([VENV_PY, '-c',
            f"import sys, json; sys.path.insert(0,'{TOOL_DIR}'); import film_library as fl; "
            f"f = fl.add_film(json.loads({payload}), nick={json.dumps(name, ensure_ascii=False)}, "
            f"short={json.dumps(short or name, ensure_ascii=False)}); "
            f"print(json.dumps(f, ensure_ascii=False))"],
            capture_output=True, text=True, timeout=15, cwd=TOOL_DIR)
        try:
            return json.loads(r2.stdout.strip())
        except Exception:
            # 入库失败不再静默：把 stderr 带回去便于排查
            result['_lib_err'] = (r2.stderr or '')[-500:]
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

        # 注意：box_spec 里的 body/strip/brand_c 等必须是真实 list/tuple，不能 str(list(...))
        # 否则 film_library.add_film 展平时会把字符串拆成字符列表，污染 box 数据
        box_spec = (list(body), list(strip), brand_c, box_name, name_c, speed, speed_c)

        code = (
            f"import sys, json; sys.path.insert(0,'{REPO}'); sys.path.insert(0,'{TOOL_DIR}'); "
            f"import film_pipeline as fp; "
            f"res = fp.run_film_from_xmp('{tmp.name}', '{key}', {json.dumps(name, ensure_ascii=False)}, "
            f"({list(body)}, {list(strip)}, {repr(brand_c)}, {json.dumps(box_name, ensure_ascii=False)}, "
            f"{repr(name_c)}, {json.dumps(speed, ensure_ascii=False)}, {repr(speed_c)}), '{CUBE_DIR}'); "
            f"print(json.dumps(res, ensure_ascii=False))"
        )
        try:
            r = subprocess.run([VENV_PY, '-c', code], capture_output=True, text=True, timeout=300)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        if r.returncode != 0:
            self._send(500, json.dumps({'error': 'XMP 解析/拟合失败', 'stderr': r.stderr[-2000:]}))
            return
        try:
            result = json.loads(r.stdout.strip())
        except Exception:
            self._send(500, json.dumps({'error': '解析失败', 'raw': r.stdout[-2000:]}))
            return
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

        code = (
            f"import sys, json; sys.path.insert(0,'{REPO}'); sys.path.insert(0,'{TOOL_DIR}'); "
            f"import film_pipeline as fp; "
            f"res = fp.run_film_from_cube('{tmp.name}', '{key}', {json.dumps(name, ensure_ascii=False)}, "
            f"({list(body)}, {list(strip)}, {repr(brand_c)}, {json.dumps(box_name, ensure_ascii=False)}, "
            f"{repr(name_c)}, {json.dumps(speed, ensure_ascii=False)}, {repr(speed_c)}), '{CUBE_DIR}'); "
            f"print(json.dumps(res, ensure_ascii=False))"
        )
        try:
            r = subprocess.run([VENV_PY, '-c', code], capture_output=True, text=True, timeout=300)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        if r.returncode != 0:
            self._send(500, json.dumps({'error': 'cube 拟合失败', 'stderr': r.stderr[-2000:]}))
            return
        try:
            result = json.loads(r.stdout.strip())
        except Exception:
            self._send(500, json.dumps({'error': '解析失败', 'raw': r.stdout[-2000:]}))
            return
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
        r = subprocess.run([VENV_PY, '-c',
            f"import sys, json; sys.path.insert(0,'{TOOL_DIR}'); import film_library as fl; "
            f"f = fl.rename_film('{key}', {json.dumps(name, ensure_ascii=False)}, "
            f"{json.dumps(nick, ensure_ascii=False) if nick else 'None'}, "
            f"{json.dumps(short, ensure_ascii=False) if short else 'None'}); "
            f"print(json.dumps(f, ensure_ascii=False))"],
            capture_output=True, text=True, timeout=15, cwd=TOOL_DIR)
        try:
            film = json.loads(r.stdout.strip())
        except Exception:
            film = None
        self._send(200, json.dumps({'ok': film is not None, 'film': film}))

    def _handle_film_delete(self, data):
        key = data.get('key', '')
        if not key:
            self._send(400, json.dumps({'error': '缺少 key'}))
            return
        r = subprocess.run([VENV_PY, '-c',
            f"import sys; sys.path.insert(0,'{TOOL_DIR}'); import film_library as fl; "
            f"print('true' if fl.delete_film('{key}') else 'false')"],
            capture_output=True, text=True, timeout=15, cwd=TOOL_DIR)
        self._send(200, json.dumps({'ok': r.stdout.strip() == 'true'}))

    def _handle_build(self, data):
        if not os.path.exists(FW):
            self._send(400, json.dumps({'error': f'找不到官方固件 {FW}'}))
            return

        out_name = data.get('out_name', 'gr3_film_mods_custom.bin')
        out_path = os.path.join(TOOL_DIR, out_name)

        # v16 管线：films = 新增槽位顺序（key 列表），顺序即机内菜单显示顺序；
        # 缺省用 build_firmware.py 的 FILMS_ORDER
        cmd = [VENV_PY, os.path.join(TOOL_DIR, 'build_firmware.py'), FW, out_path]
        # 原生颗粒引擎（Particle）：固定开启。胶片（tone 25+）复用机内「颗粒效果」菜单四档。
        # 颗粒强度不在网页选，靠机内菜单 Off/Low/Mid/High 调。
        cmd += ['--grain-native']
        films_order = data.get('films')
        if isinstance(films_order, list) and films_order:
            cmd += ['--films', ','.join(str(k) for k in films_order)]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=REPO)
        except subprocess.TimeoutExpired:
            self._send(500, json.dumps({'error': '生成超时'}))
            return

        if r.returncode != 0:
            self._send(500, json.dumps({'error': '生成失败', 'stderr': r.stderr[-2000:]}))
            return

        try:
            result = json.loads(r.stdout.strip())
        except Exception:
            s = r.stdout
            i = s.rfind('{')
            j = s.rfind('}')
            if i != -1 and j != -1 and j > i:
                try:
                    result = json.loads(s[i:j+1])
                except Exception:
                    result = {'error': '无法解析后端输出', 'raw': r.stdout[-2000:]}
            else:
                result = {'error': '无法解析后端输出', 'raw': r.stdout[-2000:]}

        # 构建成功后自动核验（跑 verify_slots16.py，确认 6 胶片 + 12分区色相 + RAW显影 + 标准模式逐字节一致）
        order = films_order if (isinstance(films_order, list) and films_order) else None
        verify = self._verify_firmware(out_path, order)
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

def main():
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'GR3 胶片滤镜工具已启动: http://localhost:{PORT}')
    print('按 Ctrl+C 停止')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')

if __name__ == '__main__':
    main()
