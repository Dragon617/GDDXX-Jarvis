"""Where a command goes after it is heard. Uses any OpenAI-compatible model the user connects
(DeepSeek, Qwen, Kimi, GLM, OpenAI, a local Ollama...); without one it just confirms what it heard.

The model, key and address live in ~/.jarvis/config.json (see config.py). Every ability the model can use
comes from tools.collect(): built-in modules plus whatever plugins are switched on."""
import json
import re
import urllib.request
from datetime import datetime

from . import config, tools

CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
ZH_MARK = re.compile(r"\s*【中文】\s*")
HISTORY = []          # recent turns, so follow-up questions make sense
KEEP = 12
try:                  # pick the thread back up after a restart, from the memory on disk
    from . import memory as _memory
    HISTORY.extend(_memory.warm_history(KEEP))
except Exception as _e:
    print(f"memory warm-up: {_e}", flush=True)


def lang():
    return config.get("reply_lang") or "en"


def system_prompt():
    name = config.user_name()
    if lang() == "zh":
        return (f"你是贾维斯，用户的私人助理，称呼用户为「{name}」。回答简短、口语化，适合直接朗读，"
                "不用 Markdown、列表或表情。用户的话来自语音识别，可能有小错误，请推断本意。")
    return ("You are J.A.R.V.I.S., the user's private assistant. Reply in English, briefly (one to three sentences) "
            f"and naturally, in a calm British butler tone suitable for reading aloud. Address the user as {name}. "
            "No Markdown, lists or emoji. The user may speak Chinese; their words come from speech recognition "
            "and may contain small errors, so infer what they meant. Speak in English only: the spoken reply must not "
            "contain Chinese characters (your voice cannot read them), so translate names into English. "
            "After the spoken reply, add one new line that starts with 【中文】 followed by a natural Chinese "
            "translation of it, shown to the user as a subtitle.")


def canned(key):
    n = config.user_name()
    en = {"offline": f"I'm sorry, {n}. I can't reach my language model at the moment.",
          "done": f"Done, {n}."}[key]
    zh = {"offline": "抱歉，我暂时连不上语言模型。", "done": "好了。"}[key]
    return (zh if lang() == "zh" else en + "\n【中文】" + zh)


def split_reply(reply: str):
    """'English reply\n【中文】中文翻译' -> (english, chinese). The English part is what gets spoken."""
    parts = ZH_MARK.split(reply, maxsplit=1)
    en = parts[0].strip()
    zh = parts[1].strip() if len(parts) > 1 else ""
    if lang() == "en" and CJK.search(en):          # model ignored the format: keep Chinese out of the voice
        en, zh = CJK.sub("", en).strip(), zh or en
    return en, zh


def answer(text: str, spoken: bool = True) -> str:
    return answer_pair(text, spoken)[0]


def answer_pair(text: str, spoken: bool = True):
    """Returns (reply to speak, Chinese translation to show)."""
    return split_reply(_answer(text, spoken))


def _answer(text: str, spoken: bool = True) -> str:
    base, key, model = config.llm()
    if not base:
        if lang() == "en":
            return (f"I heard: {text}. My language model isn't connected yet. "
                    "Open the Connect brain panel and I'll take it from there.\n【中文】我听到了，但还没接入大模型，请在「接入大脑」里设置。")
        return f"收到：{text}。还没接入大模型，请在「接入大脑」里设置。"
    from . import memory
    schemas, run, hints, force_tool = tools.collect(text)
    now = datetime.now().strftime("%A %Y-%m-%d %H:%M")
    system = system_prompt() + f" It is now {now}. Your language model is {model}; say so if asked." + hints
    msgs = [{"role": "system", "content": system}, *HISTORY, {"role": "user", "content": text}]
    try:
        for turn in range(4):                     # model may call a tool, see the result, then answer
            body = {"model": model, "messages": msgs, "temperature": 0.6}
            if schemas:
                body["tools"] = schemas
                if force_tool and turn == 0:      # e.g. a hologram request: the tool must really run
                    body["tool_choice"] = {"type": "function", "function": {"name": force_tool}}
            msg = _chat_tolerant(base, key, body)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                break
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                args = {}
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    fn = run.get(c["function"]["name"])
                    result = fn(**args) if fn else {"ok": False, "error": "unknown tool"}
                except Exception as e:
                    result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                print(f"{c['function']['name']}: {args} -> {str(result)[:300]}", flush=True)
                memory.log_work(c["function"]["name"], args, result)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, ensure_ascii=False)})
        else:
            reply = canned("done")
    except Exception as e:
        print(f"llm error: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return canned("offline")
    HISTORY.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply}])
    del HISTORY[:-KEEP]
    return reply


def remember_said(text: str):
    """Jarvis spoke on its own (a question, a reminder): keep it so the user's answer makes sense."""
    HISTORY.append({"role": "assistant", "content": text})
    del HISTORY[:-KEEP]


def _chat_tolerant(base, key, body):
    """Some providers reject a named tool_choice: fall back to 'required', then to none."""
    try:
        return _chat(base, key, body)
    except Exception:
        if "tool_choice" not in body:
            raise
    body["tool_choice"] = "required"
    try:
        return _chat(base, key, body)
    except Exception:
        body.pop("tool_choice")
        return _chat(base, key, body)


def _chat(base, key, body, timeout=40):
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]
