"""Exercise the actual panel with synthetic courses and an isolated local state directory."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from bangxue import cli, environment, panel, state


class LocalBackend:
    def __init__(self):
        self.installed = False
        self.owner = None
        self.attempts = 0
        self.calls = []

    def mark(self, name):
        if self.owner is None:
            self.owner = threading.get_ident()
        assert self.owner == threading.get_ident()
        self.calls.append(name)

    def setup(self):
        self.mark("setup")
        return {"python": "3.12", "playwright": True, "chromium": self.installed}

    def repair(self):
        self.mark("repair")
        self.installed = True

    def login(self):
        self.mark("login")

    def verify(self):
        self.mark("verify")
        return "authenticated"

    def tabs(self):
        self.mark("tabs")
        return ["安全生产", "员工培训"]

    def classes(self, tab):
        self.mark("classes")
        assert tab == "员工培训"
        return [{"wid": "omit", "title": "未选班级"}, {"wid": "sample", "title": "已选班级"}]

    def cycle(self, scope, directory, log, concurrency):
        assert concurrency == 3
        self.mark("cycle")
        assert [c["wid"] for c in state.load(scope)["classes"]] == ["sample"]
        self.attempts += 1
        phase = {1: "running", 2: "attention"}.get(self.attempts, "complete")
        state.save(directory / "sample.json", {"courses": [{"title": "练习课程", "cid": "c1"}]})
        state.save(directory / "_scope_state.json",
                   {"verified_table_version": 2, "class_evidence":{"sample":{"wid":"sample","total":1,"checked_at":1}}, "current": "sample" if phase == "running" else None,
                    "done": ["sample"] if phase == "complete" else [],
                    "skipped": {"sample": "需要人工完成练习"} if phase == "attention" else {}})
        log("已核对练习课程")
        return phase

    def resume(self, scope, directory, log):
        self.mark("resume")
        state.clear_pause(directory / "_scope_state.json")

    def pause(self, scope, directory, log):
        self.mark("pause")
        assert state.pause_requested(directory / "_scope_state.json")

    def close(self):
        self.mark("close")


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = LocalBackend()
        self.app = panel.Panel(self.tmp.name, backend=self.backend)
        self.addCleanup(self.app.close)
        self.server = panel.serve(self.app)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)

    def test_installed_chrome_is_ready_without_downloading_chromium(self):
        chrome = Path(self.tmp.name) / "chrome.exe"
        chrome.touch()
        backend = panel.BrowserBackend(Path(self.tmp.name) / "learning-profile")
        with patch.object(panel, "installed_windows_chrome", return_value=chrome), \
                patch.object(panel.importlib.util, "find_spec", return_value=True), \
                patch.object(environment, "install_browser") as install:
            self.assertTrue(backend.setup()["chromium"])
            self.assertEqual("Google Chrome", backend.setup()["browser_name"])
            self.assertEqual(chrome, backend.browser().executable_path)
            backend.repair()
            install.assert_not_called()

    def test_api_is_local_and_private(self):
        origin, token = self.server.url.split("/#")
        with self.assertRaises(HTTPError) as err:
            urlopen(origin + "/api/state")
        self.assertEqual(err.exception.code, 403)
        for bad in [{"Origin": "http://invalid.example"}, {"Host": "invalid.example"}, {"X-Panel-Token": ""}]:
            headers = {"Origin": origin, "X-Panel-Token": token, "Content-Type": "application/json", **bad}
            req = Request(origin + "/api/action", data=b'{"action":"login"}', headers=headers)
            with self.assertRaises(HTTPError) as err:
                urlopen(req)
            self.assertEqual(err.exception.code, 403)
        self.assertNotIn("login", self.backend.calls)

    def test_running_task_restores_paused_with_confirmed_classes(self):
        with self.app.cv:
            self.app.cv.wait_for(lambda: not self.app.busy, timeout=5)
        self.app.tab = "合成栏目"
        self.app.catalog = [{"wid":"sample", "title":"已选班级"}]
        self.app.submit("confirm", {"tab":self.app.tab,"ids":["sample"]})
        with self.assertRaises(panel.ActionError):
            self.app.submit("start", {"id":"old-task-from-another-tab"})
        self.app._phase("running", "运行中")
        self.app.close()
        replacement = panel.Panel(self.tmp.name, backend=LocalBackend())
        self.addCleanup(replacement.close)
        info = replacement.snapshot()
        self.assertEqual(info["task"]["phase"], "paused")
        self.assertEqual(info["task"]["rows"][0]["wid"], "sample")

    def test_agent_uses_panel_worker_and_starts_only_the_given_scope(self):
        from bangxue import panel_client

        root = Path(self.tmp.name)
        state.save(root / "window.json", {"url": self.server.url})
        context = patch.dict(os.environ, {"BANGXUE_PANEL_ROOT": str(root)})
        context.start()
        self.addCleanup(context.stop)
        result = root / "结果.json"
        cli.main(["agent", "--output", str(result), "prepare"])
        self.assertEqual("authenticated", state.load(result)["login"])
        client = panel_client.Client()
        self.assertIn("repair", self.backend.calls)
        self.assertNotIn("login", self.backend.calls)
        self.assertIn("员工培训", client.discover()["tabs"])
        self.assertEqual(["omit", "sample"], [row["wid"] for row in client.discover("员工培训")["catalog"]])
        with self.assertRaisesRegex(ValueError, "列表"):
            client.action("launch", site=client.status()["site"], tab="其他栏目", ids=["sample"], concurrency=3)
        self.assertIsNone(client.status()["task"])
        cli.main(["agent", "--output", str(result), "start", "--tab", "员工培训", "--id", "sample", "--concurrency", "3"])
        self.assertEqual("running", state.load(result)["task"]["phase"])
        running = client.wait()["task"]
        self.assertEqual("running", running["phase"])
        self.assertEqual(["sample"], [row["wid"] for row in running["rows"]])
        client.action("pause", id=running["id"])
        self.assertEqual("paused", client.wait()["task"]["phase"])
        client.action("resume", id=running["id"])
        self.assertEqual("attention", client.wait()["task"]["phase"])
        self.assertEqual("authenticated", client.prepare()["login"])
        with self.assertRaisesRegex(ValueError, "当前任务"):
            client.action("launch", tab="员工培训", ids=["sample"], concurrency=3)
        client.action("retry", id=running["id"])
        self.assertEqual("complete", client.wait()["task"]["phase"])
        self.assertEqual(1, len(client.status()["history"]))

    def test_agent_waits_for_sign_in_without_selecting_a_scope(self):
        from bangxue import panel_client

        client = panel_client.Client(self.server.url)
        with patch.object(self.backend, "verify", side_effect=["login", "opened", "authenticated"]):
            self.assertEqual("opened", client.prepare()["login"])
            self.assertEqual("opened", client.prepare()["login"])
            self.assertEqual("authenticated", client.prepare()["login"])
        self.assertEqual(1, self.backend.calls.count("login"))
        self.assertIsNone(client.status()["task"])

    def test_real_chromium_panel(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright 未安装")
        with sync_playwright() as pw:
            if not Path(pw.chromium.executable_path).exists():
                self.skipTest("Chromium 未安装")
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width":1152,"height":850})
                page.set_default_timeout(10000)
                failures, external = [], []
                page.on("pageerror", lambda exc: failures.append(str(exc)))
                def local_only(route):
                    if route.request.url.startswith(self.server.origin + "/"):
                        return route.continue_()
                    external.append(route.request.url)
                    route.abort()
                page.route("**/*", local_only)
                page.goto(self.server.url)
                expect(page.get_by_role("heading",name="学习工作台")).to_be_visible()
                expect(page.get_by_role("heading", name="任务与结果")).to_be_in_viewport()
                expect(page.get_by_role("button", name="安装 / 修复组件")).not_to_be_visible()
                page.get_by_text("手动设置", exact=True).click()
                page.get_by_role("button",name="安装 / 修复组件").click()
                page.get_by_role("button",name="打开登录窗口").click()
                page.get_by_role("button",name="检查登录").click()
                expect(page.locator("#login-hint")).to_have_text("已在学习窗口确认登录。")
                page.get_by_role("button",name="获取栏目").click()
                page.get_by_label("资源栏目").select_option("员工培训")
                page.get_by_role("button",name="读取班级").click()
                page.get_by_label("已选班级",exact=True).check()
                page.get_by_label("最多同时播放").select_option("3")
                page.get_by_role("button",name="确认学习范围").click()
                expect(page.locator("#results")).not_to_contain_text("未选班级")
                page.get_by_role("button",name="开始学习").click()
                page.get_by_role("button",name="暂停学习").click()
                expect(page.locator("#phase")).to_have_text("已暂停")
                page.reload()
                expect(page.locator("#phase")).to_have_text("已暂停")
                page.get_by_text("手动设置", exact=True).click()
                expect(page.get_by_role("button", name="继续学习")).to_be_enabled()
                from bangxue.panel_client import Client
                Client(self.server.url).action("resume", id=self.app.snapshot()["task"]["id"])
                expect(page.locator("#phase")).to_have_text("待处理")
                pending = page.locator("#results details")
                if pending.get_attribute("open") is None:
                    pending.locator("summary").click()
                expect(page.get_by_text("需要人工完成练习")).to_be_visible()
                page.get_by_role("button",name="处理后重试").click()
                expect(page.locator("#phase")).to_have_text("已完成")
                expect(page.locator("#count")).to_have_text("1 / 1")
                page.set_viewport_size({"width":375,"height":720})
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                self.assertFalse(external)
                self.assertFalse(failures)
                self.assertEqual(self.backend.attempts, 3)
            finally:
                browser.close()

# Fixtures always use a synthetic platform, even on a configured user machine.
def setUpModule():
    from unittest.mock import patch
    import os
    env = patch.dict(os.environ, {"BANGXUE_SITE_URL": "https://learning.example.test"})
    env.start()
    unittest.addModuleCleanup(env.stop)
