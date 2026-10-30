"""First-run setup, the same on macOS and Windows. Safe to run again: it only adds what is missing.

  1. a private Python environment (venv) next to the models
  2. the Python packages in requirements.txt (Tsinghua / Aliyun mirrors first, then PyPI)
  3. the speech models in app/models.json (hf-mirror first, then GitHub / ModelScope), size + sha256 checked;
     a local copy is used first when JARVIS_MODELS_FROM (or a models-bundle folder beside app/) has it

Progress shows on a small local page (http://127.0.0.1:8766) that opens in the browser, and in install.log.
Run with the Python that ships with Jarvis:  python app/install.py  [--no-page] [--models-only]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis import config, paths  # noqa: E402  (both are light: no speech models load)

VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "dev"
VENV = paths.APP / "venv"
LOG = paths.APP / "install.log"
MIRRORS = ["https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.aliyun.com/pypi/simple", "https://pypi.org/simple"]
PORT = 8766

STATE = {"version": VERSION, "step": 0, "steps": ["准备 Python 环境", "安装 Python 组件", "下载语音模型", "完成"],
         "detail": "", "file": "", "done_bytes": 0, "total_bytes": 0, "ok": None, "error": "", "log": str(LOG)}


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    STATE["detail"] = msg


def venv_python():
    return VENV / ("Scripts/python.exe" if paths.IS_WIN else "bin/python")


# ---- 1. venv -------------------------------------------------------------------------------------------
def make_venv():
    STATE["step"] = 0
    if venv_python().exists():
        log(f"Python 环境已存在：{VENV}")
        return
    log(f"创建 Python 环境：{VENV}")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)


# ---- 2. packages ---------------------------------------------------------------------------------------
def pip_install():
    STATE["step"] = 1
    py = str(venv_python())
    for args, what in ((["--upgrade", "pip"], "pip"), (["-r", str(ROOT / "requirements.txt")], "依赖")):
        for idx in MIRRORS:
            log(f"安装{what}（{idx}）…")
            p = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "--timeout", "30", "-i", idx, *args],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(p.stdout[-20000:])
            if p.returncode == 0:
                break
        else:
            raise RuntimeError(f"Python 组件安装失败（{what}），详见 {LOG}")


# ---- 3. models -----------------------------------------------------------------------------------------
def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _good(dest, e):
    if not dest.exists() or dest.stat().st_size == 0:
        return False
    if e.get("size") and dest.stat().st_size != e["size"]:
        return False
    return not e.get("sha256") or _sha(dest) == e["sha256"]


def _fetch(url, dest, expect=0):
    """Download with resume. Raises on failure."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": f"Jarvis/{VERSION} (+install)",
                                               **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        if have and r.status != 206:
            have = 0                                   # server ignored the range: start over
        total = have + int(r.headers.get("Content-Length") or 0)
        STATE.update(file=dest.name, done_bytes=have, total_bytes=total or expect)
        with open(part, "ab" if have else "wb") as f:
            while True:
                b = r.read(1 << 18)
                if not b:
                    break
                f.write(b)
                STATE["done_bytes"] += len(b)
    os.replace(part, dest)


def _extract(t, dest):
    try:
        t.extractall(dest, filter="data")              # safe extraction (Python 3.12, and recent 3.10/3.11 patches)
    except TypeError:                                  # older 3.10/3.11: no filter argument
        t.extractall(dest)


def _from_archive(url, members, models):
    """Pull files out of a .tar.bz2 / .zip release. members: {name inside (basename): destination}."""
    with tempfile.TemporaryDirectory() as td:
        arc = Path(td) / url.rsplit("/", 1)[-1].split("?")[0]
        _fetch(url, arc)
        out = Path(td) / "x"
        if arc.suffix == ".zip":
            with zipfile.ZipFile(arc) as z:
                z.extractall(out)
        else:
            with tarfile.open(arc) as t:
                _extract(t, out)
        for p in out.rglob("*"):
            if p.is_file() and p.name in members:
                members[p.name].parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), members[p.name])


def models():
    STATE["step"] = 2
    man = json.loads((ROOT / "app" / "models.json").read_text(encoding="utf-8"))
    groups = {"core", "zh" if (config.get("voice_lang") or os.environ.get("JARVIS_LANG") or "en") == "zh" else "en"}
    M = paths.MODELS
    M.mkdir(parents=True, exist_ok=True)
    todo = [e for e in man["files"] if e.get("group", "core") in groups]
    local = [Path(x) for x in (os.environ.get("JARVIS_MODELS_FROM"), ROOT / "models-bundle") if x and Path(x).is_dir()]
    tried = set()                            # each release archive is fetched at most once
    for i, e in enumerate(todo, 1):
        dest = M / e["path"]
        if _good(dest, e):
            continue
        for src in local:                       # an offline copy (USB stick, a bundled folder) wins over the network
            if (src / e["path"]).is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src / e["path"], dest)
                if _good(dest, e):
                    log(f"本地复制模型：{e['path']}")
                    break
        if _good(dest, e):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        log(f"下载模型 {i}/{len(todo)}：{e['path']}")
        ok = False
        for url in e.get("urls", []):
            try:
                _fetch(url, dest, e.get("size", 0))
                ok = _good(dest, e)
                if ok:
                    break
                got = dest.stat().st_size if dest.exists() else 0
                log(f"  文件校验不通过（{got} 字节，sha256 {_sha(dest)[:16] if got else '-'}），换一个来源：{url}")
                dest.unlink(missing_ok=True)
            except Exception as ex:
                log(f"  {url} 不可用：{type(ex).__name__}")
        for arc in [a for a in (e.get("zip"), e.get("archive")) if a and not ok]:
            if arc in tried:
                continue
            tried.add(arc)
            try:
                log(f"  从压缩包取出：{arc}")
                same = [x for x in todo if arc in (x.get("zip"), x.get("archive")) and not _good(M / x["path"], x)]
                _from_archive(arc, {Path(x["path"]).name: M / x["path"] for x in same}, M)
                ok = _good(dest, e) or (dest.exists() and not e.get("sha256"))
                if ok:
                    break
            except Exception as ex:
                log(f"  {arc} 不可用：{type(ex).__name__}")
        if not ok:
            if e.get("optional"):
                log(f"  跳过可选模型 {e['path']}（之后再打开 Jarvis 会再试）")
                continue
            raise RuntimeError(f"模型下载失败：{e['path']}。请检查网络后重新打开 Jarvis。")
    if "en" in groups and not any(_good(M / e["path"], e) for e in todo if e["path"].endswith((".onnx",)) and
                                  e["path"].startswith(("jarvis/", "alan/"))):
        raise RuntimeError("贾维斯的声音模型没有下载下来（jarvis-high 和备用的 alan 都失败了）。请检查网络后重新打开 Jarvis。")
    for d in man.get("dirs", []):
        if d.get("group") in groups and not (M / d["dir"]).exists():
            log(f"下载模型文件夹 {d['dir']}")
            with tempfile.TemporaryDirectory() as td:
                arc = Path(td) / "a.tar.bz2"
                _fetch(d["archive"], arc)
                with tarfile.open(arc) as t:
                    _extract(t, M)


# ---- page ------------------------------------------------------------------------------------------------
PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Jarvis 安装</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#02050a;color:#dcefF7;
font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.box{width:min(520px,calc(100vw - 32px));padding:28px;border:1px solid rgba(127,219,255,.3);border-radius:14px;background:rgba(4,12,18,.9)}
h1{margin:0 0 4px;font-weight:400;letter-spacing:.2em;font-size:20px}h1 small{font-size:10px;letter-spacing:.3em;color:#7fdbff;margin-left:8px}
ol{padding-left:20px;color:#5e7f8d}li.now{color:#e8f5fa}li.done{color:#6fe3b8}
.bar{height:6px;border-radius:3px;background:rgba(127,219,255,.12);overflow:hidden;margin:8px 0}.bar i{display:block;height:100%;width:0;background:#7fdbff;transition:width .4s}
.d{color:#a3c0cc;font-size:12.5px;word-break:break-all}.err{color:#ffae6b;white-space:pre-wrap}</style></head><body><div class="box">
<h1>J.A.R.V.I.S<small>SETUP</small></h1><p class="d">第一次打开需要准备一下（只需一次）。语音模型约 1 GB，下载完成后全部在本机运行。</p>
<ol id="steps"></ol><div class="bar"><i id="bar"></i></div><div class="d" id="detail"></div><div class="err" id="err"></div></div>
<script>
async function tick(){try{const s=await (await fetch('/status',{cache:'no-store'})).json();
document.getElementById('steps').innerHTML=s.steps.map((t,i)=>`<li class="${i<s.step||s.ok?'done':i===s.step?'now':''}">${t}</li>`).join('');
const pct=s.total_bytes?Math.min(100,s.done_bytes/s.total_bytes*100):(s.ok?100:0);
document.getElementById('bar').style.width=pct+'%';
document.getElementById('detail').textContent=s.ok?'安装完成，Jarvis 正在打开。这个页面可以关掉了。':s.detail+(s.total_bytes?`  ${(s.done_bytes/1048576).toFixed(0)} / ${(s.total_bytes/1048576).toFixed(0)} MB`:'');
if(s.ok===false){document.getElementById('err').textContent='安装没有完成：'+s.error+'\\n日志：'+s.log+'\\n关掉这个页面，重新打开 Jarvis 会从断点继续。';return}
if(!s.ok)setTimeout(tick,700)}catch(e){setTimeout(tick,1500)}}tick();</script></body></html>"""


class Page(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps(STATE).encode() if self.path.startswith("/status") else PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if self.path.startswith("/status") else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def page():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Page)
    except OSError:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    webbrowser.open(f"http://127.0.0.1:{PORT}/")
    return srv


def installed():
    try:
        return (paths.APP / "installed").read_text().strip() == VERSION and venv_python().exists()
    except Exception:
        return False


def run(show_page=True, models_only=False):
    paths.APP.mkdir(parents=True, exist_ok=True)
    srv = page() if show_page else None
    log(f"=== Jarvis {VERSION} setup, {sys.platform}, Python {sys.version.split()[0]} ===")
    try:
        if not models_only:
            make_venv()
            pip_install()
        models()
        if not models_only:
            (paths.APP / "installed").write_text(VERSION)
        STATE.update(step=3, ok=True, detail="完成")
        log("安装完成")
        return True
    except Exception as e:
        STATE.update(ok=False, error=str(e)[:400])
        log(f"!!! {type(e).__name__}: {e}")
        return False
    finally:
        if srv:
            time.sleep(3 if STATE["ok"] else 120)      # leave a failure on screen for a while
            srv.shutdown()


if __name__ == "__main__":
    ok = run(show_page="--no-page" not in sys.argv, models_only="--models-only" in sys.argv)
    sys.exit(0 if ok else 1)
