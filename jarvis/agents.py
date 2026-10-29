"""What the HUD's Agent panel shows: the helpers Jarvis hands work to, and what each is doing right now.

  brain    the deep brain (DeepSeek Harness, plugin harness): a conversation in the brain window
  jobs     background jobs from ask_harness (documents, programs, files)
  learn    abilities on the learning list and trial abilities waiting for the user's approval
  review   the nightly review of the day and its open suggestions

snapshot() -> {"type": "agents", "items": [{"id", "name", "desc", "state", "progress"}]}
state: off (not available) · idle · run (working now) · warn (needs the user) · done (finished recently)."""
import time

from . import tools


def _brain(h):
    if not h or not h.available():
        return {"state": "off", "desc": "未安装 DeepSeek Harness"}
    B = h.brainlink.BRAIN
    if B.busy:
        tab = next(iter(B.busy_tabs), "default")
        return {"state": "run", "desc": "处理中 · " + (B.asked.get(tab, "") or "…")[:40]}
    if getattr(B, "perm_tab", None):
        return {"state": "warn", "desc": "等你批准一个操作"}
    return {"state": "idle", "desc": "空闲 · 复杂的事交给我"}


def _jobs(h):
    if not h or not h.available():
        return {"state": "off", "desc": "未安装 DeepSeek Harness"}
    jobs = sorted(h.JOBS.values(), key=lambda j: j["started"])
    work = [j for j in jobs if j["state"] == "working"]
    if work:
        j = work[-1]
        mins = (time.time() - j["started"]) / 60
        return {"state": "run", "desc": f"{len(work)} 个进行中 · {j['task'][:30]}",
                "progress": min(0.95, mins / (h.LIMIT / 60))}
    if jobs and time.time() - jobs[-1]["started"] < 3 * 3600:
        j = jobs[-1]
        return {"state": "done" if j["state"] == "done" else "warn",
                "desc": ("已完成 · " if j["state"] == "done" else "没完成 · ") + j["task"][:30]}
    return {"state": "idle", "desc": "空闲 · 做文档、程序、表格"}


def _learn():
    from . import skills
    try:
        trial = skills.listing().get("trial", [])
        items = skills.learning()
    except Exception:
        return {"state": "idle", "desc": "—"}
    building = [i for i in items if i.get("state") == "building"]
    approved = [i for i in items if i.get("state") == "approved"]
    new = [i for i in items if i.get("state") == "new"]
    if trial:
        return {"state": "warn", "desc": f"{len(trial)} 个新能力等你批准安装"}
    if building:
        return {"state": "run", "desc": "正在学 · " + str(building[0].get("what", ""))[:30]}
    if approved:
        return {"state": "idle", "desc": f"{len(approved)} 项已批准，今晚学"}
    return {"state": "idle", "desc": f"学习清单 {len(new)} 项" if new else "还没有要学的"}


def _review():
    from . import review
    try:
        ideas = sum(len([p for p in r.get("proposals", []) if p.get("state") == "new"]) for r in review.pending())
        last = review.load(review._day(1))
    except Exception:
        return {"state": "idle", "desc": "—"}
    if ideas:
        return {"state": "warn", "desc": f"{ideas} 条改进建议等你看"}
    if last and not last.get("error"):
        return {"state": "done", "desc": f"已复盘 {last.get('day', '')[5:]} · 没有问题" if not last.get("empty") else "昨天没什么可复盘"}
    return {"state": "idle", "desc": "每晚 1 点复盘当天"}


AGENTS = [("brain", "BRAIN", "大脑"), ("jobs", "JOBS", "后台任务"), ("learn", "LEARNING", "学习"), ("review", "REVIEW", "复盘")]


def snapshot():
    h = tools.plugin("harness")
    parts = {"brain": lambda: _brain(h), "jobs": lambda: _jobs(h), "learn": _learn, "review": _review}
    items = []
    for aid, name, zh in AGENTS:
        try:
            info = parts[aid]()
        except Exception as e:
            info = {"state": "idle", "desc": f"{type(e).__name__}"}
        items.append({"id": aid, "name": name, "zh": zh, **info})
    return {"type": "agents", "items": items}
