# -*- coding: utf-8 -*-
"""
局域网文件共享（LanShare）
把本机的一个文件夹，通过同一 Wi-Fi / 局域网共享给手机、平板、其他电脑。
手机扫二维码或输入网址即可浏览、下载（可选上传）。

双击同目录的 LanShare.exe 运行（或 python LanShare.pyw）。仅在本机监听，不做任何外网穿透。
"""

import os
import io
import re
import sys
import json
import mmap
import socket
import tempfile
import mimetypes
import threading
import queue
import urllib.parse
import subprocess
import traceback
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

if getattr(sys, "frozen", False):
    # 打包成 exe 后 __file__ 指向临时解压目录，配置必须跟着 exe 本身走，
    # 否则每次启动都会“忘记”上次的文件夹和端口。
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
ERROR_LOG = os.path.join(APP_DIR, "error.log")
FIREWALL_RULE = "LanShare File Share (LAN)"

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText
except Exception:
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write("[%s] tkinter 不可用：\n%s\n" % (datetime.now(), traceback.format_exc()))
    sys.exit(1)

try:
    import qrcode
except Exception:
    qrcode = None


# ---------------------------------------------------------------- 工具函数

def fmt_size(n):
    if n is None:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    v = float(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return "%d B" % int(v)
    return "%.1f %s" % (v, units[i])


def fmt_time(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def file_icon(name, is_dir):
    if is_dir:
        return "📁"
    ext = os.path.splitext(name)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"):
        return "🖼️"
    if ext in (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".rmvb"):
        return "🎬"
    if ext in (".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg"):
        return "🎵"
    if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
        return "🗜️"
    if ext in (".pdf",):
        return "📕"
    if ext in (".doc", ".docx", ".wps"):
        return "📘"
    if ext in (".xls", ".xlsx", ".csv"):
        return "📗"
    if ext in (".ppt", ".pptx"):
        return "📙"
    if ext in (".apk", ".exe", ".msi"):
        return "📦"
    if ext in (".txt", ".md", ".log", ".json", ".xml", ".py", ".js", ".html", ".htm", ".css"):
        return "📄"
    return "📎"


def get_lan_ips():
    """返回本机所有可能被局域网访问的 IPv4 地址（过滤虚拟网卡）。"""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    # UDP 探测拿默认出口 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.insert(0, ip)
        else:
            ips.remove(ip)
            ips.insert(0, ip)
    except Exception:
        pass

    # 过滤回环 / 链路本地 / 虚拟网卡网段
    bad_prefix = ("127.", "169.254.", "192.168.252.", "192.168.192.", "172.17.", "10.0.2.")
    out = []
    for ip in ips:
        if ip.startswith(bad_prefix):
            continue
        out.append(ip)
    return out or ["127.0.0.1"]


def port_free(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", p))
        s.close()
        return True
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return False


# 80 = 手机上不用输端口号；其余是按键最好按、最好念的备选
PORT_CANDIDATES = (80, 8080, 8888, 6666, 9999)


def pick_port(preferred):
    """返回 (最终端口, 被迫替换掉的端口或 None)。"""
    if preferred and port_free(preferred):
        return preferred, None
    for p in PORT_CANDIDATES:
        if p != preferred and port_free(p):
            return p, preferred
    for p in range(10001, 10201):
        if port_free(p):
            return p, preferred
    return 0, preferred


def url_for(ip, port):
    """80 端口不写出来，手机上少输几个字符。"""
    try:
        port = int(port)
    except Exception:
        return "http://%s/" % ip
    if port == 80:
        return "http://%s/" % ip
    return "http://%s:%d/" % (ip, port)


def run_hidden(cmd, timeout=20):
    """静默执行外部命令。

    GUI 程序（没有控制台）直接 subprocess 调 netsh 这类控制台程序时，
    Windows 会给子进程新开一个控制台窗口 —— 用户看到的就是一闪而过的黑框。
    必须显式指定 CREATE_NO_WINDOW 把它掐掉。
    """
    kw = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        try:
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kw["startupinfo"] = si
    return subprocess.run(cmd, **kw)


def resource_path(name):
    """取资源文件（图标等）。打包成 exe 后资源在 sys._MEIPASS，源码运行时就近取。"""
    for base in (getattr(sys, "_MEIPASS", None), APP_DIR):
        if base:
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    return ""


def in_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def firewall_rule_exists():
    try:
        r = run_hidden(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=" + FIREWALL_RULE],
            timeout=15)
        return r.returncode == 0 and "No rules match" not in r.stdout.decode("gbk", "replace")
    except Exception:
        return False


def add_firewall_rule():
    """添加入站放行规则（需要管理员权限）。

    按端口放行、不绑定具体程序：exe 版和 Python 源码版的进程路径不同，
    绑定 program 会导致换个启动方式就失效。
    """
    if firewall_rule_exists():
        return True, "防火墙规则已存在"
    ports = ",".join(str(p) for p in PORT_CANDIDATES)
    cmd = [
        "netsh", "advfirewall", "firewall", "add", "rule",
        "name=" + FIREWALL_RULE,
        "dir=in", "action=allow", "protocol=TCP",
        "localport=" + ports,
        "profile=private",
        "enable=yes",
    ]
    try:
        r = run_hidden(cmd, timeout=30)
        if r.returncode == 0:
            return True, "防火墙已放行"
        return False, (r.stdout + b" " + r.stderr).decode("gbk", "replace").strip()
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- HTML 模板

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#060a12">
<title>%TITLE%</title>
<style>
:root{--bg:#060a12;--card:#0b1420;--line:#16344a;--txt:#cfe6f2;--sub:#5d7f96;
 --pri:#22e1ff;--deep:#04080e;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--txt);
 background-image:radial-gradient(900px 420px at 50% -160px,rgba(34,225,255,.10),transparent 70%);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;}
header{position:sticky;top:0;z-index:9;background:rgba(6,10,18,.92);
 backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line);padding:12px 15px;}
h1{margin:0;font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px;
 color:var(--pri);letter-spacing:.4px}
h1 .n{font-weight:400;font-size:12px;color:var(--sub);letter-spacing:0}
.crumb{font-size:12px;color:var(--sub);margin-top:6px;word-break:break-all;line-height:1.7}
.crumb a{color:var(--pri);text-decoration:none}
main{padding:10px 12px 34px;max-width:900px;margin:0 auto}
ul{list-style:none;margin:0;padding:0;background:var(--card);border-radius:4px;
 border:1px solid var(--line);overflow:hidden}
li{display:flex;align-items:center;gap:11px;padding:13px 14px;border-bottom:1px solid rgba(22,52,74,.55)}
li:last-child{border-bottom:none}
li:active{background:#0f1c2b}
li a{flex:1;color:var(--txt);text-decoration:none;word-break:break-all;min-width:0}
.ico{font-size:19px;width:24px;text-align:center;flex:none;line-height:1}
.meta{font-size:11.5px;color:var(--sub);flex:none;margin-left:auto;padding-left:8px;
 white-space:nowrap;text-align:right;font-family:ui-monospace,Consolas,monospace}
.meta b{display:block;font-weight:400}
.empty{text-align:center;color:var(--sub);padding:56px 0;background:var(--card);
 border-radius:4px;border:1px solid var(--line)}
form.up{margin-top:12px;background:var(--card);border-radius:4px;padding:14px;
 border:1px solid var(--line)}
form.up .t{font-size:13px;color:var(--sub);margin-bottom:10px;
 font-family:ui-monospace,Consolas,monospace}
input[type=file]{width:100%;font-size:13px;margin-bottom:11px;color:var(--sub)}
input[type=file]::file-selector-button{padding:8px 14px;border:1px solid var(--line);
 border-radius:3px;background:var(--deep);color:var(--pri);font-size:13px;margin-right:10px;
 font-family:inherit}
button{width:100%;padding:12px;border:0;border-radius:3px;background:var(--pri);color:#04121a;
 font-size:15px;font-weight:700;font-family:inherit;letter-spacing:3px}
button:active{opacity:.85}
footer{text-align:center;color:var(--sub);font-size:11.5px;padding:16px 0 30px;line-height:1.8;
 font-family:ui-monospace,Consolas,monospace}
.toast{background:rgba(34,225,255,.08);border:1px solid var(--line);
 border-left:2px solid var(--pri);color:var(--pri);border-radius:3px;padding:11px 13px;
 font-size:13px;margin-bottom:12px}
</style>
</head>
<body>
<header>
  <h1>%H1%</h1>
  <div class="crumb">%CRUMB%</div>
</header>
<main>%BODY%</main>
<footer>LANSHARE // LOCAL FILE RELAY<br>仅限本机所在网络访问 · %FOOT%</footer>
</body>
</html>"""


def page(title, h1, crumb, body, foot=""):
    return (PAGE.replace("%TITLE%", title)
                .replace("%H1%", h1)
                .replace("%CRUMB%", crumb)
                .replace("%BODY%", body)
                .replace("%FOOT%", foot))


# ---------------------------------------------------------------- HTTP 处理

def safe_path(root, rel):
    rel = urllib.parse.unquote(rel or "/")
    rel = rel.replace("\\", "/").lstrip("/")
    p = os.path.abspath(os.path.join(root, rel))
    root = os.path.abspath(root)
    if p == root or p.startswith(root + os.sep):
        return p
    return None


def unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    target = os.path.join(directory, filename)
    i = 1
    while os.path.exists(target):
        target = os.path.join(directory, "%s(%d)%s" % (base, i, ext))
        i += 1
        if i > 999:
            break
    return target


class ShareHandler(BaseHTTPRequestHandler):
    server_version = "LanShare/1.0"
    protocol_version = "HTTP/1.1"

    root = ""
    allow_upload = True
    log = None

    # ---- 基础设施

    def log_message(self, fmt, *args):
        if ShareHandler.log:
            try:
                ShareHandler.log("%s %s" % (self.address_string(), fmt % args))
            except Exception:
                pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None, head_only=False):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if not head_only and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _err(self, code, msg):
        self._send(code, page("出错了", "出错了",
                              urllib.parse.quote(self.path),
                              '<div class="empty">%s</div>' % msg))

    # ---- GET

    def do_GET(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            target = safe_path(self.root, parsed.path)
            if target is None:
                self._err(403, "路径不合法")
                return
            if os.path.isdir(target):
                self._send(200, self.render_dir(parsed.path, target))
            elif os.path.isfile(target):
                self.send_file(target)
            else:
                self._err(404, "没有找到：%s" % self.path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            if ShareHandler.log:
                ShareHandler.log("处理请求出错：\n" + traceback.format_exc())
            try:
                self._err(500, "服务器内部错误")
            except Exception:
                pass

    def do_HEAD(self):
        try:
            target = safe_path(self.root, urllib.parse.urlsplit(self.path).path)
            if target and os.path.isfile(target):
                st = os.stat(target)
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(st.st_size))
                self.end_headers()
            else:
                self._send(404, "", head_only=True)
        except Exception:
            pass

    # ---- 文件发送（支持 Range，方便手机上拖进度条看视频）

    def send_file(self, path):
        st = os.stat(path)
        size = st.st_size
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        inline = ctype.startswith(("image/", "video/", "audio/", "text/")) or ctype == "application/pdf"
        disp = "inline" if inline else "attachment"

        start, end = 0, size - 1
        partial = False
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and size > 0:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Last-Modified", self.date_time_string(st.st_mtime))
        self.send_header("Content-Disposition",
                         "%s; filename*=UTF-8''%s" % (disp, urllib.parse.quote(name)))
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- 目录页

    def render_dir(self, urlpath, abspath):
        if not urlpath.endswith("/"):
            urlpath += "/"
        rel = urllib.parse.unquote(urlpath).strip("/")
        # 面包屑
        parts = [p for p in rel.split("/") if p]
        crumb = ['<a href="/">◢ 根目录</a>']
        acc = ""
        for p in parts:
            acc += "/" + urllib.parse.quote(p)
            crumb.append('<a href="%s/">%s</a>' % (acc, p))
        crumb_html = " / ".join(crumb)

        try:
            entries = list(os.scandir(abspath))
        except PermissionError:
            return page("无权限", "无权限", crumb_html,
                        '<div class="empty">这个文件夹打不开（权限不足）</div>')

        dirs = [e for e in entries if e.is_dir(follow_symlinks=False)]
        files = [e for e in entries if e.is_file(follow_symlinks=False)]
        dirs.sort(key=lambda e: e.name.lower())
        files.sort(key=lambda e: e.name.lower())

        items = []
        if parts:
            parent = "/" + "/".join(urllib.parse.quote(x) for x in parts[:-1])
            if not parent.endswith("/"):
                parent += "/"
            items.append('<li><span class="ico">↩️</span><a href="%s">返回上一级</a></li>' % parent)

        for e in dirs:
            if e.name.startswith("$"):
                continue
            try:
                st = e.stat()
                ts = fmt_time(st.st_mtime)
            except Exception:
                ts = ""
            items.append(
                '<li><span class="ico">📁</span>'
                '<a href="%s/">%s</a>'
                '<span class="meta">%s</span></li>'
                % (urllib.parse.quote(e.name), e.name, ts))

        for e in files:
            try:
                st = e.stat()
                meta = '<b>%s</b><b>%s</b>' % (fmt_size(st.st_size), fmt_time(st.st_mtime))
            except Exception:
                meta = ""
            items.append(
                '<li><span class="ico">%s</span>'
                '<a href="%s">%s</a>'
                '<span class="meta">%s</span></li>'
                % (file_icon(e.name, False), urllib.parse.quote(e.name), e.name, meta))

        if items:
            body = "<ul>%s</ul>" % "".join(items)
        else:
            body = '<div class="empty">这个文件夹是空的</div>'

        if ShareHandler.allow_upload:
            body += (
                '<form class="up" method="post" action="%s" enctype="multipart/form-data">'
                '<div class="t">把手机里的文件上传到这个文件夹</div>'
                '<input type="file" name="files" multiple>'
                '<button type="submit">上传</button></form>' % urlpath)

        n = len(dirs) + len(files)
        return page(rel or "共享文件夹", "📂 %s" % (os.path.basename(abspath.rstrip("\\/")) or "共享文件夹"),
                    crumb_html, body, "%d 个项目" % n)

    # ---- POST 上传

    def do_POST(self):
        if not ShareHandler.allow_upload:
            self._err(403, "当前未开启上传功能")
            return
        target_dir = safe_path(self.root, urllib.parse.urlsplit(self.path).path)
        if not target_dir or not os.path.isdir(target_dir):
            self._err(400, "上传目标不合法")
            return
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._err(400, "上传格式不支持")
            return
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            self._err(400, "缺少 boundary")
            return
        boundary = m.group(1).encode("utf-8")

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._err(400, "空内容")
            return

        saved = []
        tmp_name = None
        try:
            # 先把请求体流式落到临时文件（避免大文件吃内存）
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_name = tmp.name
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    tmp.write(chunk)
                    left -= len(chunk)

            with open(tmp_name, "rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    delim = b"--" + boundary
                    pos = mm.find(delim)
                    while pos != -1:
                        head_start = pos + len(delim)
                        if mm[head_start:head_start + 2] == b"--":
                            break
                        # 跳过 CRLF
                        if mm[head_start:head_start + 2] == b"\r\n":
                            head_start += 2
                        head_end = mm.find(b"\r\n\r\n", head_start)
                        if head_end == -1:
                            break
                        header_txt = mm[head_start:head_end].decode("utf-8", "replace")
                        data_start = head_end + 4
                        next_pos = mm.find(delim, data_start)
                        if next_pos == -1:
                            break
                        data_end = next_pos
                        if mm[data_end - 2:data_end] == b"\r\n":
                            data_end -= 2

                        fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]*)"?', header_txt, re.I)
                        filename = fn_match.group(1).strip() if fn_match else ""
                        if filename:
                            filename = urllib.parse.unquote(filename)
                            filename = os.path.basename(filename.replace("\\", "/"))
                            filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(". ")
                            if filename:
                                out = unique_path(target_dir, filename)
                                with open(out, "wb") as of:
                                    of.write(mm[data_start:data_end])
                                saved.append(os.path.basename(out))
                        pos = next_pos
                finally:
                    mm.close()
        except Exception:
            if ShareHandler.log:
                ShareHandler.log("上传出错：\n" + traceback.format_exc())
            self._err(500, "上传失败")
            return
        finally:
            if tmp_name and os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except Exception:
                    pass

        if ShareHandler.log:
            ShareHandler.log("收到上传：%s" % ("、".join(saved) if saved else "无文件"))

        back = urllib.parse.urlsplit(self.path).path
        note = urllib.parse.quote("已上传 %d 个文件" % len(saved)) if saved else ""
        self.send_response(303)
        self.send_header("Location", back + ("?ok=" + note if note else ""))
        self.send_header("Content-Length", "0")
        self.end_headers()


# ---------------------------------------------------------------- 科幻配色

UI = {
    "bg":       "#060a12",   # 深空底
    "panel":    "#0b1420",   # 面板
    "deep":     "#04080e",   # 更深（输入框 / 日志）
    "line":     "#16344a",   # 描边
    "cyan":     "#22e1ff",   # 主霓虹
    "cyan_dk":  "#0b7f96",
    "magenta":  "#ff2e88",   # 停止 / 危险
    "green":    "#25f5a5",
    "text":     "#cfe6f2",
    "sub":      "#5d7f96",
}
F_UI = ("Microsoft YaHei UI", 10)
F_TAG = ("Consolas", 9, "bold")
F_VAL = ("Consolas", 12, "bold")
F_BTN = ("Microsoft YaHei UI", 11, "bold")
F_LOG = ("Consolas", 9)


def enable_dark_titlebar(root):
    """把 Windows 标题栏也刷成深色（Win10 1809+ 支持），否则浅色标题栏配深色内容很跳。"""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):     # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def neon_panel(parent, title):
    """科幻面板：细描边框 + ◈ 标签条。返回 (外框, 内容区)。"""
    outer = tk.Frame(parent, bg=UI["panel"],
                     highlightbackground=UI["line"], highlightthickness=1)
    bar = tk.Frame(outer, bg=UI["panel"])
    bar.pack(fill="x", padx=11, pady=(8, 0))
    tk.Label(bar, text="◈", font=("Consolas", 9, "bold"),
             bg=UI["panel"], fg=UI["cyan"]).pack(side="left")
    tk.Label(bar, text="  " + title, font=F_TAG,
             bg=UI["panel"], fg=UI["sub"]).pack(side="left")
    body = tk.Frame(outer, bg=UI["panel"])
    body.pack(fill="both", expand=True, padx=11, pady=(7, 11))
    return outer, body


# ---------------------------------------------------------------- 主界面

class App:
    def __init__(self, root):
        self.tk = root
        self.server = None
        self.thread = None
        self.q = queue.Queue()
        self.cfg = self.load_cfg()

        root.title("LANSHARE · 局域网文件共享")
        root.geometry("568x756")
        root.minsize(548, 710)
        root.configure(bg=UI["bg"])
        ico = resource_path("LanShare.ico")
        if ico:
            try:
                root.iconbitmap(default=ico)      # 顶掉 tkinter 自带的羽毛图标
            except Exception:
                pass

        pad = {"padx": 16}
        self._pulse_on = False

        # ── 标题
        head = tk.Frame(root, bg=UI["bg"])
        head.pack(fill="x", pady=(16, 0), **pad)
        row = tk.Frame(head, bg=UI["bg"])
        row.pack(fill="x")
        self.led = tk.Canvas(row, width=12, height=12, bg=UI["bg"], highlightthickness=0)
        self.led.pack(side="left", pady=(5, 0))
        self.led_id = self.led.create_oval(1, 1, 11, 11, fill=UI["cyan_dk"], outline="")
        tk.Label(row, text="  LANSHARE", font=("Consolas", 20, "bold"),
                 bg=UI["bg"], fg=UI["cyan"]).pack(side="left")
        tk.Label(row, text="v1.0", font=("Consolas", 9),
                 bg=UI["bg"], fg=UI["sub"]).pack(side="left", padx=(9, 0), pady=(7, 0))
        tk.Label(head, text="LOCAL FILE RELAY   //   局域网文件共享", font=("Consolas", 9),
                 bg=UI["bg"], fg=UI["sub"]).pack(anchor="w", pady=(1, 0))

        tk.Frame(root, bg=UI["line"], height=1).pack(fill="x", pady=(11, 13), **pad)

        # ── 共享文件夹
        p1, b1 = neon_panel(root, "共享文件夹  /  SHARE PATH")
        p1.pack(fill="x", **pad)
        self.var_dir = tk.StringVar(value=self.cfg.get("folder", ""))
        tk.Entry(b1, textvariable=self.var_dir, font=("Consolas", 10),
                 bg=UI["deep"], fg=UI["text"], insertbackground=UI["cyan"],
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=UI["line"], highlightcolor=UI["cyan"]).pack(
            side="left", fill="x", expand=True, ipady=6)
        tk.Button(b1, text="选择…", command=self.pick_dir, font=F_UI,
                  bg=UI["deep"], fg=UI["cyan"], activebackground=UI["cyan_dk"],
                  activeforeground="#04121a", relief="flat", bd=0, cursor="hand2",
                  highlightthickness=1, highlightbackground=UI["line"]).pack(
            side="left", padx=(8, 0), ipady=3, ipadx=4)

        # ── 端口 / 上传
        p2, b2 = neon_panel(root, "端口与权限  /  PORT & ACCESS")
        p2.pack(fill="x", pady=(11, 0), **pad)
        self.var_port = tk.StringVar(value=str(self.cfg.get("port", 80)))
        self.ent_port = tk.Entry(b2, textvariable=self.var_port, width=5,
                                 font=("Consolas", 11, "bold"), justify="center",
                                 bg=UI["deep"], fg=UI["cyan"], insertbackground=UI["cyan"],
                                 relief="flat", bd=0, highlightthickness=1,
                                 highlightbackground=UI["line"], highlightcolor=UI["cyan"])
        self.ent_port.pack(side="left", ipady=5)
        self.ent_port.bind("<FocusOut>", lambda e: self.on_port_change())
        self.ent_port.bind("<Return>", lambda e: self.on_port_change())
        tk.Label(b2, text=" 80 = 网址免输端口", font=F_TAG,
                 bg=UI["panel"], fg=UI["sub"]).pack(side="left", padx=(9, 16))
        self.var_upload = tk.BooleanVar(value=bool(self.cfg.get("upload", True)))
        tk.Checkbutton(b2, text="允许手机上传", variable=self.var_upload,
                       command=self.on_upload_toggle, font=F_UI,
                       bg=UI["panel"], fg=UI["text"], activebackground=UI["panel"],
                       activeforeground=UI["cyan"], selectcolor=UI["deep"],
                       highlightthickness=0, bd=0, cursor="hand2").pack(side="left")

        # ── 主按钮
        self.btn_start = tk.Button(root, text="▶   启 动 共 享", command=self.toggle,
                                   font=F_BTN, bg=UI["cyan"], fg="#04121a",
                                   activebackground="#8bf2ff", activeforeground="#04121a",
                                   relief="flat", bd=0, cursor="hand2",
                                   highlightthickness=0)
        self.btn_start.pack(fill="x", pady=(13, 0), ipady=8, **pad)

        # ── 接入端点（二维码 + 网址）
        p3, b3 = neon_panel(root, "接入端点  /  ACCESS POINT")
        p3.pack(fill="x", pady=(11, 0), **pad)

        self.qr = tk.Canvas(b3, width=178, height=178, bg="#ffffff",
                            highlightthickness=1, highlightbackground=UI["cyan"])
        self.qr.pack(pady=(2, 9))

        self.var_url = tk.StringVar(value="未启动")
        self.lbl_url = tk.Label(b3, textvariable=self.var_url, font=("Consolas", 13, "bold"),
                                bg=UI["panel"], fg=UI["cyan"], cursor="hand2")
        self.lbl_url.pack()
        self.lbl_url.bind("<Button-1>", lambda e: self.copy_url())

        self.lbl_alt = tk.Label(b3, text="", font=("Microsoft YaHei UI", 9),
                                bg=UI["panel"], fg=UI["sub"], justify="center")
        self.lbl_alt.pack(pady=(5, 0))

        # ── 运行日志
        p4, b4 = neon_panel(root, "运行日志  /  SYSLOG")
        p4.pack(fill="both", expand=True, pady=(11, 16), **pad)
        self.logbox = ScrolledText(b4, height=7, font=F_LOG,
                                   bg=UI["deep"], fg="#7fd4e8",
                                   insertbackground=UI["cyan"],
                                   relief="flat", bd=0, wrap="word")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.tag_configure("ts", foreground=UI["cyan_dk"])
        self.logbox.configure(state="disabled")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tk.after(120, self.drain)
        self.pulse()

        # 窗口高度贴着内容走：小屏幕上自动收缩，免得日志区被压扁
        enable_dark_titlebar(root)
        self.fit_height()
        self.tk.after(80, self.fit_height)      # 布局彻底完成后校正一次
        self.tk.after(450, self.fit_height)

        self.print_log("系统就绪 // 选好文件夹后点「启动共享」")
        self.check_firewall_async()

    # ---- 配置

    def load_cfg(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            default = os.path.join(os.path.expanduser("~"), "Desktop")
            return {"folder": default if os.path.isdir(default) else os.path.expanduser("~"),
                    "port": 80, "upload": True}

    def save_cfg(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({"folder": self.var_dir.get(), "port": self.var_port.get(),
                           "upload": self.var_upload.get()}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---- 日志

    def print_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "[%s] " % ts, "ts")
        self.logbox.insert("end", "%s\n" % msg)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.print_log(msg)
        except queue.Empty:
            pass
        self.tk.after(150, self.drain)

    def pulse(self):
        """顶部状态灯：运行中绿青呼吸，停止时暗青。"""
        if self.server:
            self._pulse_on = not self._pulse_on
            color = UI["green"] if self._pulse_on else UI["cyan_dk"]
        else:
            color = UI["cyan_dk"]
        try:
            self.led.itemconfigure(self.led_id, fill=color)
        except Exception:
            pass
        self.tk.after(650, self.pulse)

    def fit_height(self):
        """把窗口高度调到刚好容下内容（下界 720，上界给任务栏留 90px）。

        必须在 pack 全部完成后才算得准，所以启动时会调用两次。
        """
        try:
            self.tk.update_idletasks()
            need = self.tk.winfo_reqheight()
            h = min(max(need + 40, 720), self.tk.winfo_screenheight() - 90)
            self.tk.geometry("568x%d" % h)
        except Exception:
            pass

    def thread_log(self, msg):
        self.q.put(msg)

    # ---- 交互

    def pick_dir(self):
        init = self.var_dir.get() or os.path.expanduser("~")
        if not os.path.isdir(init):
            init = os.path.expanduser("~")
        d = filedialog.askdirectory(title="选择要共享的文件夹", initialdir=init)
        if d:
            self.set_folder(os.path.normpath(d))

    def set_folder(self, new):
        old = self.var_dir.get()
        if new == old:
            return
        self.var_dir.set(new)
        self.save_cfg()
        if self.server:
            # 已经在跑就立刻切过去，不用重启、不用重新扫码
            ShareHandler.root = new
            self.print_log("共享文件夹已切换为：%s" % new)
            self.print_log("手机上刷新一下页面就能看到新文件夹。")
            self.update_alt()
        else:
            self.print_log("已选择文件夹：%s（点「启动共享」开始）" % new)

    def on_upload_toggle(self):
        ShareHandler.allow_upload = bool(self.var_upload.get())
        self.save_cfg()
        if self.server:
            self.print_log("上传功能：%s" % ("开启" if ShareHandler.allow_upload else "关闭"))

    def on_port_change(self):
        self.save_cfg()
        if not self.server:
            return
        try:
            want = int(self.var_port.get().strip())
        except ValueError:
            return
        if want == getattr(self, "cur_port", None):
            return
        self.print_log("端口改成 %d，正在重新启动服务…" % want)
        self.stop_server()
        self.start_server()

    def copy_url(self):
        url = self.var_url.get()
        if url.startswith("http"):
            self.tk.clipboard_clear()
            self.tk.clipboard_append(url)
            self.print_log("网址已复制到剪贴板")
            self.lbl_alt.configure(text="已复制到剪贴板")

    def check_firewall_async(self):
        def work():
            if firewall_rule_exists():
                self.thread_log("防火墙：已放行（规则存在）")
                return
            ok, msg = add_firewall_rule()
            if ok:
                self.thread_log("防火墙：已放行 80 / 8080 / 8888 / 6666 / 9999")
            else:
                self.thread_log("防火墙：需要手动放行。若手机打不开，"
                                "请在弹出的安全提示中点「允许访问」，"
                                "或右键以管理员身份运行「修复防火墙.bat」。")
        threading.Thread(target=work, daemon=True).start()

    # ---- 启动 / 停止

    def toggle(self):
        if self.server:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        folder = self.var_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("路径不对", "请先选择一个存在的文件夹")
            return
        try:
            port = int(self.var_port.get().strip())
            if not (1 < port < 65536):
                raise ValueError
        except ValueError:
            messagebox.showwarning("端口不对", "端口要是 1~65535 之间的数字")
            return

        port, replaced = pick_port(port)
        if not port:
            messagebox.showerror("端口不可用", "找不到可用端口，请手动换一个")
            return
        if replaced:
            self.print_log("端口 %d 被占用，已自动改用 %d" % (replaced, port))
            self.var_port.set(str(port))

        folder = os.path.abspath(folder)
        ShareHandler.root = folder
        ShareHandler.allow_upload = bool(self.var_upload.get())
        ShareHandler.log = self.thread_log

        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", port), ShareHandler)
        except Exception as e:
            messagebox.showerror("启动失败", "无法监听端口 %d：%s" % (port, e))
            return
        httpd.daemon_threads = True
        self.server = httpd
        self.thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self.thread.start()

        ips = get_lan_ips()
        self.cur_ips = ips
        self.cur_port = port
        url = url_for(ips[0], port)
        self.var_url.set(url)
        self.show_qr(url)
        self.update_alt()

        self.btn_start.configure(text="■   停 止 共 享", bg=UI["magenta"],
                                 activebackground="#ff6aa6", fg="#1a0410")
        self.print_log("已启动：%s" % url)
        self.print_log("共享目录：%s" % folder)
        self.print_log("上传功能：%s" % ("开启" if ShareHandler.allow_upload else "关闭"))
        self.save_cfg()

    def update_alt(self):
        """刷新网址下方那行说明（切换文件夹时也要跟着变）。"""
        if not self.server:
            self.lbl_alt.configure(text="")
            return
        ips = getattr(self, "cur_ips", None) or get_lan_ips()
        port = getattr(self, "cur_port", 80)
        if port == 80:
            alt = "手机上直接输入 %s 就行，不用带端口" % ips[0]
        else:
            alt = "手机和电脑要在同一个 Wi-Fi 下"
        alt += "\n共享：%s" % ShareHandler.root
        others = [i for i in ips[1:]]
        if others:
            alt += "\n其他网卡：" + "、".join(url_for(o, port) for o in others)
        alt += "\n（点上方网址可复制）"
        self.lbl_alt.configure(text=alt)

    def stop_server(self):
        if not self.server:
            return
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
        self.server = None
        self.thread = None
        self.btn_start.configure(text="▶   启 动 共 享", bg=UI["cyan"],
                                 activebackground="#8bf2ff", fg="#04121a")
        self.var_url.set("未启动")
        self.lbl_alt.configure(text="")
        self.qr.delete("all")
        self.print_log("已停止共享")

    def on_close(self):
        self.save_cfg()
        if self.server:
            self.stop_server()
        self.tk.destroy()

    # ---- 二维码

    def show_qr(self, url):
        c = self.qr
        c.delete("all")
        if qrcode is None:
            c.create_text(90, 90, text="未安装二维码库\n请手动输入网址", fill="#8a919f",
                          font=("Microsoft YaHei UI", 10), justify="center", width=160)
            return
        try:
            qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(url)
            qr.make(fit=True)
            m = qr.get_matrix()
            n = len(m)
            # canvas 固定 178x178，这里只负责把码居中画进去（留 1 格白边）
            cell = max(1, 178 // (n + 2))
            off = (178 - cell * n) // 2
            for y, row in enumerate(m):
                for x, v in enumerate(row):
                    if v:
                        c.create_rectangle(off + x * cell, off + y * cell,
                                           off + (x + 1) * cell, off + (y + 1) * cell,
                                           fill="#0a0f16", outline="")
        except Exception:
            c.create_text(90, 90, text=url, fill="#2b6cf6", font=("Consolas", 9),
                          width=160, justify="center")


def main():
    root = tk.Tk()
    app = App(root)
    # 默认不自动共享；加 --autostart 参数才会打开即开始（给开机自启/自动化用）
    if "--autostart" in sys.argv:
        root.after(400, app.start_server)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("[%s]\n%s\n" % (datetime.now(), traceback.format_exc()))
        try:
            messagebox.showerror("程序出错", traceback.format_exc()[-800:])
        except Exception:
            pass
