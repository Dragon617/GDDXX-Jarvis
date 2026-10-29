"""Wake phrase text checks, ported from the old Jarvis wake-phrase.js.

KWS gives a fast acoustic hit; this second check runs on the ASR text so TV
audio or a sentence that merely sounds close does not wake Jarvis.
"""
import re

STRONG = [
    "jarvis", "javis", "jarviss", "jarves", "jarvice", "jarvas", "jervis",
    "贾维斯", "加维斯", "扎维斯", "嘉维斯", "假维斯", "佳维斯", "家维斯", "杰维斯", "贾维思",
    "贾威斯", "贾伟思", "杰维思", "贾维丝", "贾维司", "佳伟斯", "家伟斯", "扎维丝", "扎维思",
    "扎维司", "炸维斯", "查维斯", "贾维士", "加微斯", "佳微斯", "嘉微斯", "贾薇斯", "賈維斯",
    "贾维诗", "贾维史", "甲维斯", "假威斯", "加威斯", "贾韦斯", "加维思", "佳维思",
]
PREFIX = ["hi", "hey", "hello", "嗨", "嘿", "hai", "海", "害", "还", "喂", "哎", "你好"]
_PUNCT = re.compile(r"[\s\"'`~!@#$%^&*()_+\-=\[\]{};:,.<>/?\\|，。！？、；：“”‘’（）【】《》…—]")


def compact(text: str) -> str:
    return _PUNCT.sub("", (text or "").lower())


_GREET = re.compile(r"^\s*(?:hi|hey|hay|hello|hallo|hai|嗨|嘿)(?![a-z])[\s,，.。!！?？~～-]*", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*|[\u4e00-\u9fff]+")
_NOT_NAME = {"everyone", "everybody", "guys", "all", "there", "folks", "friends", "you", "i", "i'm", "im", "it's",
             "its", "this", "that", "so", "and", "the", "a", "an", "how", "what", "welcome", "today", "good", "my", "we"}


def greet_wake(text: str):
    """'Hi <anything>' as a wake: the name after the greeting is often misheard (Travis, Joey, Jovis, Davis...).
    Returns (woke, command). Short utterances ('Hi.', 'Hi a book') wake with no command; 'Hi Travis, open the
    light' wakes with 'open the light'; long greetings to other people ('Hi everyone, welcome...') do not wake."""
    raw = (text or "").strip()
    g = _GREET.match(raw)
    if not g:
        return False, ""
    rest = raw[g.end():]
    words = _WORD.findall(rest)
    if not words:
        return True, ""
    first = words[0]
    namey = first.lower() not in _NOT_NAME and (first[:1].isupper() or not first.isascii() or len(words) <= 2)
    if not namey:
        return (len(words) <= 2), ""
    at = rest.find(first) + len(first)
    cmd = re.sub(r"^[\s,，。.!！?？、:：~～'’s]+", "", rest[at:]).strip()
    if cmd.isascii() and len(_WORD.findall(cmd)) <= 1 and len(words) <= 3:
        cmd = ""
    return True, cmd


def split_wake(text: str, trusted: bool = False):
    """Return (woke, command). command is what follows the wake phrase.
    trusted=True means the acoustic detector already heard the full wake phrase, so earlier
    words (TV, chatter) may precede it and the last wake word marks where the command starts."""
    raw = text or ""
    low = raw.lower()
    best = None
    for tok in STRONG:
        i = low.rfind(tok) if trusted else low.find(tok)
        if i >= 0 and (best is None or (i > best[0] if trusted else i < best[0])):
            best = (i, i + len(tok))
    if best is None:
        # fuzzy Chinese hypothesis: 贾/加/嘉 + 维/威 + 斯/思/丝/司 within the first 8 chars
        m = re.search(r"[贾加扎嘉假家杰佳甲][维威薇微伟韦为卫唯][斯思丝司士诗史死]", low[:12])
        if not m:
            return greet_wake(raw)      # claude-greet-wake
        best = (m.start(), m.end())
    # the wake phrase must open the utterance (allow a greeting before it)
    head = "" if trusted else compact(low[: best[0]])
    latin = low[best[0]:best[1]].isascii()
    if head and not any(head == compact(p) for p in PREFIX) and len(head) > (4 if latin else 2):
        return False, ""
    cmd = raw[best[1]:]
    cmd = re.sub(r"^[\s,，。.!！?？、:：~～]+", "", cmd).strip()
    return True, cmd
