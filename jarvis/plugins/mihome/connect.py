"""Connect Jarvis to Mi Home (米家) once:  python -m jarvis.plugins.mihome.connect [cn|de|us|ru|tw|sg|in|i2]

1. Shows a QR code; scan it with the Mi Home app (no password is typed anywhere).
2. Saves each device's local key to ~/.jarvis/mihome.json on this computer only, readable by this user only,
   so Jarvis can switch devices directly over the home Wi-Fi from then on.

Login uses Piotr Machowski's Xiaomi-cloud-tokens-extractor (MIT, token_extractor.py beside this file)."""
import json
import sys
from pathlib import Path

from ... import config, platforms
from ...paths import DATA

SAVE = DATA / "mihome.json"
SERVER = (sys.argv[1] if len(sys.argv) > 1 else config.section("mihome").get("server", "cn")).lower()
sys.argv = [sys.argv[0], "-s", SERVER]          # the extractor reads its server from the command line, no prompts
sys.path.insert(0, str(Path(__file__).parent))
import token_extractor as te                    # noqa: E402


def show_qr(image_content, **_):
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / "mihome-qr.png"
    p.write_bytes(image_content)
    platforms.open_path(p)
    print("\n>>> 已经弹出一个二维码图片。请打开手机上的「米家」App，点右上角「+」旁边的扫一扫，扫这个码并确认登录。\n"
          ">>> A QR code has opened. Scan it in the Mi Home app (+ > Scan) and confirm the login.\n")


te.present_image_image = show_qr


def login():
    c = te.QrCodeXiaomiCloudConnector()
    if not c.login():
        sys.exit("登录没有成功，可以再运行一次。Login failed, please try again.")
    return c


def devices(c):
    homes = []
    h = c.get_homes(SERVER)
    for x in (h or {}).get("result", {}).get("homelist", []) or []:
        homes.append((x["id"], c.userId))
    d = c.get_dev_cnt(SERVER)
    for x in (d or {}).get("result", {}).get("share", {}).get("share_family", []) or []:
        homes.append((x["home_id"], x["home_owner"]))
    out = []
    for home_id, owner in homes:
        r = c.get_devices(SERVER, home_id, owner) or {}
        for dev in (r.get("result", {}) or {}).get("device_info") or []:
            out.append({k: dev.get(k) for k in ("name", "did", "model", "localip", "token", "mac", "isOnline")})
    return out


def main():
    devs = devices(login())
    SAVE.write_text(json.dumps(devs, ensure_ascii=False, indent=2), encoding="utf-8")
    config._private(SAVE)
    print(f"\n找到 {len(devs)} 台米家设备（密钥只保存在这台电脑：{SAVE}）/ {len(devs)} devices found:")
    for d in devs:
        print(f"  - {d['name']}  {d['model']}  IP {d['localip'] or '-'}  {'在线 online' if d.get('isOnline') else '离线 offline'}")
    print("\n完成。对贾维斯说「打开台灯」之类的话就可以控制了。门锁、灶具、水壶、路由器出于安全不会被语音控制。\n"
          "Done. Locks, cookers, kettles and routers are never switched by voice, for safety.")


if __name__ == "__main__":
    main()
