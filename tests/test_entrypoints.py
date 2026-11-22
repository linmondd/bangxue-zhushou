"""Entry points must share concurrency, verification and pause semantics."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from bangxue import cli, environment, flow, monitor, state


class EntryPoints(unittest.TestCase):
    def test_run_default_and_scheduler_mode(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["run"]).loop)
        self.assertFalse(parser.parse_args(["run", "--once"]).loop)
        self.assertTrue(parser.parse_args(["run", "--loop"]).loop)

    def test_login_requires_trusted_site_and_evidence(self):
        driver = Mock()
        driver.current_url.return_value = "https://other.invalid/"
        driver.eval.return_value = "退出登录"
        self.assertEqual(environment.login_status(driver), "unknown")
        driver.current_url.return_value = "https://learning.example.test/portal/"
        self.assertEqual(environment.login_status(driver), "authenticated")
        driver.eval.return_value = "我的专题班 获取验证码"
        self.assertEqual(environment.login_status(driver), "login")
        driver.eval.return_value = "正在加载"
        self.assertEqual(environment.login_status(driver), "unknown")

    def test_failed_browser_install_keeps_downloader_output(self):
        try:
            from playwright._impl import _driver
        except ImportError:
            self.skipTest("需要可选 Playwright 依赖")

        def fail(command, **kwargs):
            kwargs["stdout"].write(b"Download failed: certificate rejected\n")
            self.assertEqual(subprocess.STDOUT, kwargs["stderr"])
            raise subprocess.CalledProcessError(1, command)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(Path, "home", return_value=Path(tmp)), \
                patch.object(_driver, "compute_driver_executable", return_value=("node", "cli.js")), \
                patch.object(environment.subprocess, "run", side_effect=fail):
            log = Path(tmp) / ".bangxue" / "browser-install.log"
            with self.assertRaisesRegex(RuntimeError, "browser-install.log"):
                environment.install_browser()
            self.assertIn("certificate rejected", log.read_text(encoding="utf-8"))

    def test_both_frontends_respect_total_cap_and_failure(self):
        try:
            from bangxue import mcp_server
        except (SystemExit, ImportError):
            self.skipTest("需要可选 MCP 依赖")
        rows = [{"cid": str(i), "title": f"课{i}", "manual": i == 2} for i in range(8)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(flow, "sync_done", return_value={"3"}), \
                patch.object(cli, "get_driver", return_value=Mock()), patch.object(mcp_server, "_browser", return_value=Mock()):
            for mode in ("cli", "mcp"):
                with self.subTest(mode=mode):
                    path = str(Path(tmp) / (mode + ".json"))
                    st = state.init_state("class", rows, 4)
                    st.update(active=["0","1"], done=["4"])
                    state.save(path, st)
                    with patch.object(flow,"start", side_effect=[
                            {"ok": True, "owned_tabs":[{"id": "p4", "url":"u4"}]},
                            {"ok": False, "stage": "blocked", "reason":"captcha"}]) as start:
                        if mode == "cli":
                            cli.main(["start","--state",path,"--concurrency","4"])
                        else:
                            mcp_server.bangxue_start(path,4)
                    saved = state.load(path)
                    self.assertEqual(start.call_count, 2)
                    self.assertEqual({call.args[1] for call in start.call_args_list}, {"4","5"})
                    self.assertEqual(saved["paused_reason"], "captcha")
                    self.assertEqual(set(saved["active"]), {"0","1","4"})
                    self.assertEqual(saved["done"], ["3"])
                    self.assertEqual(saved["owned_tabs"], [{"id":"p4","url":"u4"}])

    def test_cap_counts_existing_active(self):
        rows = [{"cid":str(i), "title":str(i)} for i in range(8)]
        st = state.init_state("class", rows)
        st["active"] = ["0", "1"]
        with patch.object(flow, "sync_done", return_value=set()), patch.object(flow,"start",return_value={"ok": True}):
            flow.start_pending(None, st, 5, log=lambda _: None)
        self.assertEqual(len(st["active"]), 5)

    def test_real_mcp_stdio_negotiation_and_readonly_status(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("需要可选 MCP 依赖")
        async def run(path):
            params = StdioServerParameters(command=sys.executable, args=["-m","bangxue.mcp_server"])
            async with stdio_client(params) as (reader, writer), ClientSession(reader,writer) as sess:
                await sess.initialize()
                names = {tool.name for tool in (await sess.list_tools()).tools}
                self.assertTrue({"bangxue_run","bangxue_stop","bangxue_resume"} <= names)
                result = await sess.call_tool("bangxue_status", {"state":str(path)})
                self.assertFalse(result.isError)
                self.assertIn("已确认 1 门", result.content[0].text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"state.json"
            path.write_text(json.dumps({"courses":[{"cid":"1"}],"done":["1"]}))
            asyncio.run(run(path))

# Fixtures always use a synthetic platform, even on a configured user machine.
def setUpModule():
    from unittest.mock import patch
    import os
    env = patch.dict(os.environ, {"BANGXUE_SITE_URL": "https://learning.example.test"})
    env.start()
    unittest.addModuleCleanup(env.stop)
