"""Agent access to the same authenticated loopback service as the result view."""
import json
import re
import sys
import time
from http.client import HTTPConnection

from . import panel, state


class Client:
    def __init__(self, url=None):
        if url is None:
            root = panel.panel_root()
            if not (root / "window.json").is_file():
                raise RuntimeError("请先启动帮学助手，或以 panel --background 在后台启动。")
            url = panel._existing_url(root)
        match = re.fullmatch(r"http://127[.]0[.]0[.]1:([0-9]{1,5})/#([A-Za-z0-9_-]{43})", url)
        if not match or not 0 < int(match[1]) <= 65535:
            raise ValueError("本机助手连接信息无效。")
        self.port = int(match[1])
        self.token = match[2]

    def _request(self, path, payload=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"X-Panel-Token": self.token}
        try:
            if payload is None:
                conn.request("GET", path, headers=headers)
            else:
                headers.update(Origin=f"http://127.0.0.1:{self.port}", **{"Content-Type": "application/json"})
                conn.request("POST", path, json.dumps(payload).encode("utf-8"), headers)
            response = conn.getresponse()
            content = response.read().decode("utf-8")
            if response.status == 409:
                raise ValueError(content)
            if response.status != 200:
                raise RuntimeError("本机助手连接已失效，请重新打开助手。")
            return json.loads(content)
        finally:
            conn.close()

    def status(self):
        return self._request("/api/state")

    def action(self, name, **data):
        self._request("/api/action", {**data, "action": name})

    def wait(self):
        until = time.monotonic() + 30
        while True:
            info = self.status()
            if not info["busy"] or time.monotonic() >= until:
                return info
            time.sleep(0.15)

    def prepare(self, url=None):
        info = self.wait()
        if info["busy"] or (info["task"] or {}).get("phase") == "running":
            return info
        self.action("prepare", **({"url": url} if url is not None else {}))
        return self.wait()

    def discover(self, tab=None):
        info = self.prepare()
        if not ready(info) or (info["task"] or {}).get("phase") == "running":
            return info
        if tab:
            self.action("classes", tab=tab)
        else:
            self.action("tabs")
        return self.wait()


def ready(info):
    return not info["busy"] and not info["error"] and info["login"] == "authenticated"


def run(operation, *, url=None, tab=None, ids=None, all_classes=False, concurrency=1):
    client = Client()
    if operation == "status":
        return client.status()
    if operation == "prepare":
        return client.prepare(url)
    if operation == "discover":
        return client.discover(tab)
    info = client.status()
    if operation == "start":
        if not tab or bool(ids) == bool(all_classes):
            raise ValueError("请指定栏目和班级，或明确授权该栏目的全部班级。")
        if (info["task"] or {}).get("phase") in {"ready", "paused", "attention", "running"}:
            raise ValueError("当前任务尚未结束，请继续或处理该任务。")
        if info["tab"] != tab or not info["catalog"]:
            info = client.discover(tab)
        else:
            info = client.prepare()
        if not ready(info):
            return info
        selected = [row["wid"] for row in info["catalog"]] if all_classes else ids
        client.action("launch", site=info["site"], tab=tab, ids=selected, concurrency=concurrency)
    else:
        if operation not in {"pause", "resume", "retry"}:
            raise ValueError("操作无效。")
        task = info["task"]
        if not task:
            raise ValueError("当前没有学习任务。")
        if operation != "pause":
            info = client.prepare()
            if not ready(info):
                return info
        client.action(operation, id=task["id"])
    # Long-running task work remains with the panel worker after the Agent exits.
    return client.status()


def cli(args):
    output = getattr(args, "output", None)
    if sys.stdout is None and output is None:
        raise ValueError("桌面版命令请用 --output 指定 JSON 结果文件。")
    try:
        info = run(args.operation, url=getattr(args, "url", None), tab=getattr(args, "tab", None),
                   ids=getattr(args, "ids", None), all_classes=getattr(args, "all_classes", False),
                   concurrency=getattr(args, "concurrency", 1))
    except (OSError, RuntimeError, ValueError) as exc:
        info = {"error": str(exc)}
    if output is not None:
        state.save(output, info)
    else:
        print(json.dumps(info, ensure_ascii=False))
    if info["error"]:
        return "attention"


def add_parser(sub):
    command = sub.add_parser("agent", help="让 Agent 操作本机学习任务并读取 JSON 结果")
    command.add_argument("--output", help="将 JSON 写入本机文件（桌面版可用）")
    actions = command.add_subparsers(dest="operation", required=True)
    actions.add_parser("status", help="读取当前任务、结果和待处理事项")
    actions.add_parser("prepare", help="检查环境与登录").add_argument("--url", help="学习平台 HTTPS 地址")
    actions.add_parser("discover", help="读取栏目或班级").add_argument("--tab", help="读取指定栏目的班级")
    start = actions.add_parser("start", help="开始已授权的学习范围")
    start.add_argument("--tab", required=True, help="资源栏目")
    scope = start.add_mutually_exclusive_group(required=True)
    scope.add_argument("--id", dest="ids", action="append", help="获授权的班级编号，可重复传入")
    scope.add_argument("--all", dest="all_classes", action="store_true", help="获授权处理该次读取的全部班级")
    start.add_argument("--concurrency", type=int, choices=(1, 3, 5, 10), default=1)
    actions.add_parser("pause", help="暂停当前任务")
    actions.add_parser("resume", help="继续已暂停的任务")
    actions.add_parser("retry", help="复查待处理任务")
    command.set_defaults(fn=cli)
