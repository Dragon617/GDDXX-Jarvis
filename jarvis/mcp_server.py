"""Jarvis's tools for its brain, as a stdio MCP server (python3 <this file>; it imports only memory.py and skills.py).

The brain (DeepSeek Harness) starts this for every session. It gets read access to Jarvis's memory and learning list,
the list of abilities, and a test runner for the abilities it builds. It cannot install anything: only the user can."""
import json, os, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import memory, skills          # the package import is light: no speech models load

TOOLS = [
    {"name": "jarvis_memory_search", "description": "Search Jarvis's long-term memory: earlier conversations with the user and every job Jarvis did.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD, today, yesterday"}}}},
    {"name": "jarvis_learning_list", "description": "Things Jarvis told the user it cannot do yet, with how often they were asked, and which the user approved for learning (state: new, approved, building, learned, rejected).",
     "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}}},
    {"name": "jarvis_learning_update", "description": "Mark a learning-list item as being built ('building') and link it to the trial skill folder that will provide it.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "skill": {"type": "string"}}, "required": ["id", "skill"]}},
    {"name": "jarvis_skills", "description": "Jarvis's abilities: those installed (usable by voice) and those in trial waiting for the user's approval.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "jarvis_skill_test", "description": "Run a trial skill's test.json against its tool.py and report each case. Use after every change; a skill can only be installed when this passes.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "the folder name in skills-trial"}}, "required": ["name"]}},
]


def call(name, a):
    if name == "jarvis_memory_search":
        return memory.search(a.get("query", ""), a.get("date", ""))
    if name == "jarvis_learning_list":
        return {"ok": True, "items": skills.learning(a.get("state") or None)}
    if name == "jarvis_learning_update":
        items = skills._learn_load()
        for it in items:
            if it["id"] == a.get("id"):
                it["state"], it["skill"] = "building", a.get("skill", "")
                skills._learn_save(items)
                return {"ok": True, "item": it}
        return {"ok": False, "error": "no such item"}
    if name == "jarvis_skills":
        return {"ok": True, **skills.listing()}
    if name == "jarvis_skill_test":
        return skills.test(a.get("name", ""), "trial")
    return {"ok": False, "error": f"unknown tool {name}"}


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except Exception:
            continue
        mid, method, p = m.get("id"), m.get("method"), m.get("params") or {}
        if mid is None:
            continue                                  # notifications (initialized, cancelled) need no answer
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": p.get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "jarvis", "version": "1"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                res = call(p.get("name"), p.get("arguments") or {})
                err = isinstance(res, dict) and res.get("ok") is False
            except Exception:
                res, err = {"ok": False, "error": traceback.format_exc()[-1200:]}, True
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}], "isError": err}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}})


if __name__ == "__main__":
    main()
