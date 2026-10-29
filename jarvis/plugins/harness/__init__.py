"""Hands bigger jobs (writing documents, building programs, working with files) to DeepSeek Harness, if it is installed.

Jarvis runs the Harness one-shot mode, `dsh --profile headless "<task>"`, in the background inside the workspace
folder (Desktop/Jarvis 作品 by default), so whatever it makes lands there. Headless mode ignores the keys saved in the
Harness app, so the DeepSeek key from ~/.jarvis/config.json is passed in the environment (never written
anywhere). Steps that would need someone to click "allow" are refused by Harness itself in this mode.
Full output of each job: ~/.jarvis/harness/<time>.log."""
import json, os, subprocess, threading, time
from pathlib import Path

import shutil
from ... import config
from ...paths import DATA, IS_MAC, workspace

LOGS = DATA / "harness"


def dsh():
    """The Harness command line: config.json harness.path, $JARVIS_DSH, the macOS app, or `dsh` on the PATH."""
    for c in (config.section("harness").get("path"), os.environ.get("JARVIS_DSH"),
              "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh" if IS_MAC else None):
        if c and Path(c).expanduser().exists():
            return Path(c).expanduser()
    w = shutil.which("dsh")
    return Path(w) if w else None
LIMIT = 40 * 60              # seconds before a job is stopped
NOTIFY = None                # set by the service: NOTIFY(task, ok, answer) once a job ends
JOBS = {}                    # id -> {"task", "state", "started", "answer"}

BRIEF = ("You were asked by voice through Jarvis, the user's assistant, so nobody is watching this run. "
         "The current directory is the user's 'Jarvis 作品' folder on the Desktop: save every file you create there (a new folder for a "
         "multi-file project) and do not touch files outside it, with clear names in the user's language. Do not delete or overwrite existing files. "
         "When you finish, reply with two or three sentences: what you made and the exact file names.\n\nTask: ")


def available():
    return dsh() is not None


def _env():
    from ... import brain
    base, key, _ = config.llm()
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    if key and "deepseek" in (base or ""):
        env["DEEPSEEK_API_KEY"] = key
    return env


def start(task):
    if not available():
        return {"ok": False, "error": "DeepSeek Harness is not installed"}
    jid = time.strftime("%m%d-%H%M%S")
    JOBS[jid] = {"task": task, "state": "working", "started": time.time(), "answer": ""}
    threading.Thread(target=_run, args=(jid, task), daemon=True).start()
    return {"ok": True, "job": jid, "note": "DeepSeek Harness is working on it in the background and saves to the 'Jarvis 作品' workspace folder. "
                                            "Tell the user it has started; you will report when it finishes. Do not claim it is done."}


def _run(jid, task):
    job = JOBS[jid]
    LOGS.mkdir(parents=True, exist_ok=True)
    workspace().mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{jid}.log"
    print(f"harness {jid} start: {task[:200]}", flush=True)
    try:
        with open(log, "w", encoding="utf-8") as err:
            err.write(f"task: {task}\n\n")
            err.flush()
            p = subprocess.run([str(dsh()), "--profile", "headless", BRIEF + task], cwd=workspace(), env=_env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, timeout=LIMIT, text=True)
            err.write(f"\n\nexit {p.returncode}\n--- answer ---\n{p.stdout}")
        ok = p.returncode == 0 and p.stdout.strip()
        answer = p.stdout.strip() or _tail(log)
    except subprocess.TimeoutExpired:
        ok, answer = False, f"stopped after {LIMIT // 60} minutes"
    except Exception as e:
        ok, answer = False, f"{type(e).__name__}: {e}"
    job.update(state="done" if ok else "failed", answer=answer[:4000])
    print(f"harness {jid} {'done' if ok else 'failed'} in {time.time() - job['started']:.0f}s: {answer[:300]!r}", flush=True)
    if NOTIFY:
        NOTIFY(task, bool(ok), answer[:4000])


def _tail(path, n=600):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def status():
    now = time.time()
    return {"ok": True, "jobs": [{"job": j, "task": v["task"][:120], "state": v["state"],
                                  "minutes": round((now - v["started"]) / 60, 1), "result": v["answer"][:600]}
                                 for j, v in JOBS.items()] or "no jobs yet"}


def tools():
    if not available():
        return []
    return [
        {"type": "function", "function": {
            "name": "ask_harness",
            "description": "Hand a task to DeepSeek Harness, the AI agent installed on this computer. It can write documents and "
                           "copy, build programs and web pages, make charts, slides and spreadsheets, and create or edit files; "
                           "results are saved in the 'Jarvis 作品' workspace folder. Use it for anything you can't do with your other tools. It runs in "
                           "the background (often several minutes) and the user is told when it finishes.",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "the complete task in the user's language (usually Chinese), with "
                                                          "every detail they gave: what to make, content, length, style, file type"}},
                "required": ["task"]}}},
        {"type": "function", "function": {
            "name": "harness_jobs",
            "description": "What DeepSeek Harness is working on or has finished, with its results.",
            "parameters": {"type": "object", "properties": {}}}},
    ]


def run(name, args):
    if name == "ask_harness":
        return start(args.get("task", ""))
    if name == "harness_jobs":
        return status()
    return {"ok": False, "error": "unknown tool"}


HINT = (" DeepSeek Harness, an AI agent on this computer, works for you through ask_harness: hand it any job beyond "
        "your own tools, such as writing documents or copy, building programs or web pages, making slides, charts, "
        "spreadsheets or other files. Pass the full task in the user's words, then say in one sentence that DeepSeek "
        "Harness has started and you will report when it is done. Never say you cannot do such a job without trying "
        "ask_harness. Use harness_jobs when asked how it is going.")


def bind(ctx):
    from . import brainlink
    brainlink.UI = ctx.ui


def provide():
    from . import brainlink
    pairs = [(t, (lambda n: lambda **a: run(n, a))(t["function"]["name"])) for t in tools()]
    if brainlink.available():
        pairs.append((brainlink.voice_tool(), brainlink.open_window))
    return pairs, HINT if tools() else ""
