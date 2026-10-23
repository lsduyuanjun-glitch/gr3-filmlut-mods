#!/usr/bin/env python3
"""GR3 胶片滤镜工具 —— 原生窗口壳（PyWebview）。

把现有的本地 Web 服务（server.py）套进一个**真正的 macOS 原生窗口**里，
用户只看到一个 app 窗口，没有浏览器、没有网址、没有端口冲突——
和第三方 GRMod 工具的观感一致。

- HTTP 服务仍在 127.0.0.1 后台运行，但完全藏在窗口内部，用户看不到；
- 窗口用系统原生 WebKit 渲染（PyWebview 的 cocoa 后端，无需额外浏览器）；
- 自动挑选空闲端口，彻底避免「端口被占用打不开」；
- 若原生窗口在当前环境不可用（例如无 GUI 会话的服务器），自动回退到浏览器，
  保证至少能用，不会白屏。
"""
import os
import sys
import time
import socket
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _pick_free_port(start=8310, tries=60):
    """从 start 起找一个空闲的 127.0.0.1 端口，彻底规避端口冲突。"""
    for p in range(start, start + tries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', p))
            s.close()
            return p
        except OSError:
            continue
    return start


class _Api:
    """暴露给前端 JS 的原生能力（window.pywebview.api.*）。

    v1.5.7 修复：WKWebView 原生窗口不处理 Content-Disposition: attachment，
    点「下载固件」静默无反应。这里提供原生保存对话框，把生成的固件
    复制到用户指定的位置。
    """

    def save_firmware(self):
        import webview
        import shutil
        import paths
        src = os.path.join(paths.OUTPUT_DIR, 'gr3_film_mods_custom.bin')
        if not os.path.exists(src):
            return {'ok': False, 'error': '固件文件不存在，请先「生成固件」'}
        win = webview.windows[0] if webview.windows else None
        if win is None:
            return {'ok': False, 'error': '窗口未就绪'}
        dest = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename='gr3_film_mods_custom.bin',
        )
        # macOS 返回路径字符串或列表（取决于后端），统一处理
        if isinstance(dest, (list, tuple)):
            dest = dest[0] if dest else None
        if not dest:
            return {'ok': False, 'error': 'cancelled'}
        try:
            shutil.copyfile(src, dest)
            return {'ok': True, 'path': dest}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': f'保存失败：{e!r}'}


def _main():
    port = _pick_free_port()
    os.environ['GR3_PORT'] = str(port)

    import server  # 顶层导入以便尽早暴露打包布局问题
    srv = server.run_server()

    # 等服务器起来（最多 5s）
    for _ in range(50):
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=0.2)
            c.close()
            break
        except OSError:
            time.sleep(0.1)

    url = f'http://127.0.0.1:{port}/'
    print(f'GR3 胶片滤镜工具已就绪: {url}')

    # —— 优先原生窗口；失败回退浏览器 ——
    try:
        import webview
        webview.create_window(
            'GR3 胶片工具',
            url=url,
            width=1200,
            height=840,
            resizable=True,
            background_color='#0e0e10',
            js_api=_Api(),
        )
        webview.start(gui='cocoa')
    except Exception as e:  # noqa: BLE001
        print(f'[窗口] 原生窗口不可用（{e!r}），回退到浏览器模式。')
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass
        # 服务已在后台线程运行；主线程阻塞保活（无 GUI 会话时如服务器环境）
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass


if __name__ == '__main__':
    _main()
