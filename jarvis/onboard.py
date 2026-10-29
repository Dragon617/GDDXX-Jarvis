"""「接入大脑」: the first thing a new user does is connect a language model. The HUD panel talks to this module
over the same WebSocket as everything else:

  -> {"type": "llm_status"}                                   <- {"type": "llm", "kind": "status", ...}
  -> {"type": "llm_models", "base_url", "api_key"?}            <- {"type": "llm", "kind": "models", "models": [...]}
  -> {"type": "llm_test", "provider", "base_url", "api_key"?, "model"}   <- {"type": "llm", "kind": "test", ...}
  -> {"type": "llm_save", "provider", "base_url", "api_key"?, "model", "name"?, "reply_lang"?}

Any OpenAI-compatible endpoint works. The key is never sent back to the window: an empty api_key means
"keep the one already saved". The test checks both a plain reply and a tool call, because every ability
Jarvis has (lights, schedule, holograms...) is a tool call; a model without tool calling can only chat."""
import json
import time
import urllib.request

from . import config

PRESETS = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
     "key_url": "https://platform.deepseek.com/api_keys", "key": True},
    {"id": "qwen", "name": "通义千问 Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus",
     "key_url": "https://bailian.console.aliyun.com/", "key": True},
    {"id": "kimi", "name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2-turbo-preview",
     "key_url": "https://platform.moonshot.cn/console/api-keys", "key": True},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash",
     "key_url": "https://open.bigmodel.cn/usercenter/apikeys", "key": True},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini",
     "key_url": "https://platform.openai.com/api-keys", "key": True},
    {"id": "ollama", "name": "Ollama（本地）", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b",
     "key_url": "https://ollama.com/download", "key": False},
    {"id": "custom", "name": "自定义 Custom", "base_url": "", "model": "", "key_url": "", "key": True},
]

PROBE_TOOL = {"type": "function", "function": {
    "name": "get_secret_number", "description": "Returns today's secret number. Call it whenever asked for the secret number.",
    "parameters": {"type": "object", "properties": {}}}}


def _key(given):
    """An empty key from the window means: keep the saved one."""
    return given if given else config.section("llm").get("api_key", "")


def status():
    c = config.section("llm")
    base, key, model = config.llm()
    return {"type": "llm", "kind": "status", "configured": bool(base and model), "provider": c.get("provider", ""),
            "base_url": base or "", "model": model or "", "has_key": bool(key), "presets": PRESETS,
            "name": config.user_name(), "reply_lang": config.get("reply_lang") or "en"}


def _get(url, key, timeout=15):
    req = urllib.request.Request(url, headers={**({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(base, key, body, timeout=40):
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]


def _why(e):
    """A short reason a person can act on."""
    code = getattr(e, "code", None)
    body = ""
    try:
        body = e.read().decode("utf-8", "replace")[:300]
    except Exception:
        pass
    if code in (401, 403):
        return "密钥不对或没有权限 (401/403)"
    if code == 404:
        return "地址或模型名不对 (404)"
    if code == 402:
        return "账户余额不足 (402)"
    if code == 429:
        return "请求太频繁或额度用完 (429)"
    if code:
        return f"服务返回 {code} {body}".strip()
    return f"连不上：{type(e).__name__}: {e}"[:300]


def models(base_url, api_key=""):
    try:
        data = _get(base_url.rstrip("/") + "/models", _key(api_key))
        ids = sorted({m.get("id") for m in data.get("data", []) if m.get("id")})
        return {"type": "llm", "kind": "models", "ok": True, "models": ids[:200]}
    except Exception as e:
        return {"type": "llm", "kind": "models", "ok": False, "models": [], "error": _why(e)}


def test(base_url, model, api_key=""):
    """Two calls: a plain reply, then a forced tool call. Returns what works and how long it took."""
    key = _key(api_key)
    out = {"type": "llm", "kind": "test", "ok": False, "chat": False, "tools": False, "ms": 0, "error": ""}
    if not base_url or not model:
        out["error"] = "请填写地址和模型名"
        return out
    t0 = time.time()
    try:
        msg = _post(base_url, key, {"model": model, "temperature": 0, "max_tokens": 20,
                                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
        out["chat"] = bool((msg.get("content") or "").strip())
        out["ms"] = int((time.time() - t0) * 1000)
        out["reply"] = (msg.get("content") or "").strip()[:60]
    except Exception as e:
        out["error"] = _why(e)
        return out
    body = {"model": model, "temperature": 0, "tools": [PROBE_TOOL],
            "messages": [{"role": "user", "content": "What is the secret number?"}]}
    for choice in ({"type": "function", "function": {"name": "get_secret_number"}}, "required", None):
        try:
            b = dict(body, **({"tool_choice": choice} if choice else {}))
            msg = _post(base_url, key, b)
            out["tools"] = any(c.get("function", {}).get("name") == "get_secret_number" for c in msg.get("tool_calls") or [])
            break
        except Exception as e:
            out["tool_error"] = _why(e)
    out["ok"] = out["chat"]
    if out["chat"] and not out["tools"]:
        out["warning"] = "这个模型能聊天，但不支持工具调用：贾维斯只能对话，开灯、日程、全息演示等能力用不了。建议换一个支持 function calling 的模型。"
    return out


def save(provider, base_url, model, api_key="", name=None, reply_lang=None):
    llm = {"provider": provider or "custom", "base_url": base_url.strip(), "model": model.strip()}
    key = _key(api_key.strip() if api_key else "")
    if key:
        llm["api_key"] = key
    changes = {"llm": llm}
    if name is not None:
        changes["name"] = name.strip() or "sir"
    if reply_lang in ("en", "zh"):
        changes["reply_lang"] = reply_lang
    config.update(**changes)
    return {**status(), "kind": "saved"}


def handle(msg):
    """One llm_* message from the window -> the reply to send back."""
    t = msg.get("type")
    if t == "llm_status":
        return status()
    if t == "llm_models":
        return models(msg.get("base_url", ""), msg.get("api_key", ""))
    if t == "llm_test":
        return test(msg.get("base_url", ""), msg.get("model", ""), msg.get("api_key", ""))
    if t == "llm_save":
        return save(msg.get("provider", ""), msg.get("base_url", ""), msg.get("model", ""), msg.get("api_key", ""),
                    msg.get("name"), msg.get("reply_lang"))
    return {"type": "llm", "kind": "error", "error": f"unknown {t}"}
