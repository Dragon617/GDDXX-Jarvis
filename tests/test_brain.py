"""Brain + onboarding against a fake OpenAI-compatible server (no network, no speech models).

    python tests/test_brain.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ["JARVIS_HOME"] = tempfile.mkdtemp()
os.environ["JARVIS_APP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEEN = []


class Fake(BaseHTTPRequestHandler):
    tools_ok = True

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good":
            return self._send({"error": "bad key"}, 401)
        self._send({"data": [{"id": "fake-1"}, {"id": "fake-2"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        if self.headers.get("Authorization") != "Bearer good":
            return self._send({"error": "bad key"}, 401)
        msgs, tools = body["messages"], body.get("tools") or []
        last = msgs[-1]
        names = [t["function"]["name"] for t in tools]

        def call(name, args):
            return {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
        if last["role"] == "tool":
            msg = {"role": "assistant", "content": "Done, sir. It is on your schedule.\n【中文】好了，已经加进日程。"}
        elif Fake.tools_ok and "get_secret_number" in names:
            msg = call("get_secret_number", {})
        elif Fake.tools_ok and "manage_schedule" in names and "meeting" in last["content"]:
            msg = call("manage_schedule", {"action": "add", "items": [{"start": "15:00", "title": "开会", "title_en": "meeting"}]})
        else:
            msg = {"role": "assistant", "content": "ready"}
        self._send({"choices": [{"message": msg}]})


def main():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    from jarvis import onboard, brain, config, schedule

    st = onboard.status()
    assert not st["configured"] and len(st["presets"]) >= 6, st
    assert onboard.models(base, "bad")["ok"] is False
    assert onboard.models(base, "good")["models"] == ["fake-1", "fake-2"]
    t = onboard.test(base, "fake-1", "bad")
    assert not t["ok"] and "401" in t["error"], t
    t = onboard.test(base, "fake-1", "good")
    assert t["ok"] and t["chat"] and t["tools"], t
    Fake.tools_ok = False
    t = onboard.test(base, "fake-1", "good")
    assert t["ok"] and not t["tools"] and t.get("warning"), t
    Fake.tools_ok = True

    r = onboard.save("custom", base, "fake-1", "good", name="Tony")
    assert r["configured"] and r["has_key"] and '"good"' not in json.dumps(r), r
    r = onboard.save("custom", base, "fake-1", "")                        # empty key keeps the saved one
    assert config.section("llm")["api_key"] == "good"
    if os.name != "nt":
        assert oct(os.stat(config.CONFIG).st_mode & 0o777) == "0o600"

    en, zh = brain.answer_pair("put a meeting at three in the afternoon")
    assert en.startswith("Done") and zh.startswith("好了"), (en, zh)
    assert [i["title_en"] for i in schedule.load()["items"]] == ["meeting"]
    sysmsg = SEEN[-2]["messages"][0]["content"]
    assert "Address the user as Tony" in sysmsg and "manage_schedule" in json.dumps(SEEN[-2]["tools"])
    print("brain + onboarding: all checks passed")


if __name__ == "__main__":
    main()
