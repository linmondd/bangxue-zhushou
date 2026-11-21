import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bangxue import classes, cli, flow, monitor, runner, state
from bangxue.drivers.base import Tab
from bangxue.drivers.webbridge import WebBridgeDriver


def setUpModule():
    env = patch.dict(os.environ, {"BANGXUE_SITE_URL": "https://learning.example.test"})
    env.start()
    unittest.addModuleCleanup(env.stop)


class FieldRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scope = str(Path(self.tmp.name) / "scope.json")
        self.directory = Path(self.tmp.name) / "states"
        state.save(self.scope, {"classes": [{"wid": "a", "title": "A"}]})
        self.driver = Mock(spec=["list_tabs", "open", "close", "verify_record"])
        self.driver.list_tabs.return_value = []
        self.driver.close.return_value = True

    def _state(self, st):
        path = self.directory / (st["workshop"] + ".json")
        state.save(path, st)
        return path

    def test_site_requires_local_configuration(self):
        with patch.dict(os.environ, {}, clear=True), patch("bangxue.site_config._path", return_value=Path(self.tmp.name) / "new.json"):
            with self.assertRaises(ValueError):
                flow.workshop_url("a")
            from bangxue import site_config
            site_config.save("https://learning.example.test")
            self.assertEqual("https://learning.example.test/workshop/#/myworkshop/detail?id=a", flow.workshop_url("a"))

    def test_completion_requires_fresh_receipt_and_queue_continues(self):
        prog = self.directory / "_scope_state.json"
        state.save(self.scope, {"classes": [{"wid": "a", "title": "A"}, {"wid": "b", "title": "B"}]})
        state.save(prog, {"done": ["a"], "verified_table_version": 2, "class_evidence": {}})
        rows = [{"title": "same", "prog": "100%"}, {"title": "same", "prog": "0%"}]
        with patch.object(classes, "read_class_table", return_value=rows), \
             patch.object(flow, "capture", return_value={"courses": [{"cid": "a1", "title": "same"}, {"cid": "a2", "title": "other"}]}), \
             patch.object(monitor, "run_one", return_value="running"):
            self.assertEqual("running", runner.run_cycle(self.driver, self.scope, self.directory))
            self.assertEqual([], state.load(prog)["done"])
        with patch.object(classes, "read_class_table", return_value=[{"title": "done", "prog": "100%"}]), patch.object(monitor, "wait_interval", return_value="running") as wait:
            state.save(self.directory / "a.json", state.init_state("a", [{"cid": "done", "title": "done"}], 1))
            self.assertEqual("complete", runner.run_loop(self.driver, self.scope, self.directory, interval_min=1))
            wait.assert_not_called()

    def test_queue_waits_then_advances_to_next_class(self):
        state.save(self.scope, {"classes": [{"wid": "a", "title": "A"}, {"wid": "b", "title": "B"}]})
        reads = iter([[{"title": "A", "prog": "0%"}], [{"title": "A", "prog": "100%"}],
                      [{"title": "B", "prog": "100%"}]])
        with patch.object(classes, "read_class_table", side_effect=lambda *args: next(reads)), \
             patch.object(flow, "capture", return_value={"courses": [{"cid": "a1", "title": "A"}]}), \
             patch.object(monitor, "run_one", return_value="running"), \
             patch.object(monitor, "wait_interval", return_value="running") as wait:
            self.assertEqual("complete", runner.run_loop(self.driver, self.scope, self.directory, interval_min=1))
            wait.assert_called_once()
        self.assertEqual(["a", "b"], state.load(self.directory / "_scope_state.json")["done"])

    def test_completion_receipt_follows_each_class(self):
        path = self.directory / "a.json"
        st = state.init_state("a", [{"cid": "one", "title": "同名"}, {"cid": "two", "title": "同名"}], 1)
        state.save(path, st)
        rows = [{"title": "同名", "prog": "100%"}, {"title": "同名", "prog": "100%"}]
        with patch.object(classes, "read_class_table", return_value=rows):
            result, _ = runner._inspect_class(Mock(), str(path), "a", "A", 1, print, {})
        self.assertEqual("attention", result)
        self.assertEqual([], state.load(path)["done"])

    def test_unproven_popup_does_not_continue_capture(self):
        driver = Mock()
        driver.close.return_value = False
        driver.current_url.return_value = flow.detail_url("x", "a")
        with patch.object(flow, "_read_capture_page", return_value={}), patch.object(flow, "_json", return_value={"row": {"title": "x"}, "x": 1, "y": 1}), patch.object(flow, "_tabs", return_value=[Tab("old", flow.workshop_url("a")), Tab("child", flow.detail_url("x", "a"))]), patch.object(flow, "_wait", return_value=(Tab("child", flow.detail_url("x", "a")), "x")):
            with self.assertRaises(flow.TableReadError):
                flow._capture_id(driver, Tab("old", flow.workshop_url("a")), "a", {"rows": [{"title": "x"}]}, 0, 1)
        self.assertNotIn("owned_tabs", {})

    def test_speed_mismatch_pauses_and_stops_starting(self):
        with patch.object(flow, "set_speed", return_value=False):
            result = flow._start_player(type("D", (), {"driver": None, "eval": lambda self, js: "ok" if "noplayer" in js and "querySelectorAll" in js else "", "hover": lambda self, x, y: None})(), Tab("id", flow.play_url("a", "b")), "a", "b", False, print)
        self.assertEqual("rate_mismatch", result["stage"])
        st = state.init_state("b", [{"cid": "a", "title": "A"}, {"cid": "c", "title": "C"}], 5)
        path = str(self._state(st))
        with patch.object(flow, "sync_done", return_value=set()), patch.object(flow, "start", return_value=result) as start:
            monitor.start_one(Mock(), path)
        self.assertEqual(1, start.call_count)
        self.assertEqual("页面倍速未同步，需要检查", state.load(path)["attention_reason"])
        self.assertTrue(state.pause_requested(path))
        self.assertEqual("paused", monitor.run_one(Mock(), path))
        state.clear_pause(path)
        state.save(path, {**state.load(path), "paused_reason": None})

    def test_buffer_reports_and_end_waits_for_table(self):
        st = state.init_state("b", [{"cid": "a", "title": "A"}], 5)
        st.update(active=["a"], verified_table_version=1, last_sync=9999999999)
        path = str(self._state(st))
        with patch.object(flow, "check", return_value={"ok": False, "stage": "blocked", "reason": "4008"}), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "recover_buffer", return_value=True), \
             patch.object(flow, "resume", return_value={}):
            self.assertEqual("attention", monitor.run_one(self.driver, path))
        self.assertIn("4008", state.load(path)["attention_reason"])
        st = state.load(path)
        st.pop("attention_reason")
        state.save(path, st)
        with patch.object(flow, "check", return_value={"ct": 60, "dur": 60, "prog": "4.5%"}), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "verify", return_value={"confirmed": False}):
            self.assertEqual("running", monitor.run_one(self.driver, path))
        self.assertEqual([], state.load(path)["done"])
        self.assertEqual(["a"], state.load(path)["active"])

    def test_buffer_recovers_once_with_lower_cap_and_reenter(self):
        st = state.init_state("b", [{"cid": "a", "title": "A"}], 5)
        st.update(active=["a"], verified_table_version=1, last_sync=9999999999)
        path = str(self._state(st))
        blocked = {"ok": False, "stage": "blocked", "reason": "4008"}
        with patch.object(flow, "check", side_effect=[blocked, {"ct": 1, "dur": 20}]), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "recover_buffer", return_value=True) as recover, \
             patch.object(time, "sleep"):
            self.assertEqual("running", monitor.run_one(self.driver, path))
            recover.assert_called_once()
        saved = state.load(path)
        self.assertEqual(1, saved["max_concurrent"])
        self.assertEqual(1, saved["recovery_attempts"]["a"])
        with patch.object(flow, "check", return_value=blocked), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "recover_buffer", return_value=True):
            self.assertEqual("attention", monitor.run_one(self.driver, path))
        self.assertIn("4008", state.load(path)["attention_reason"])

    def test_finished_video_waits_for_table_before_replay(self):
        st = state.init_state("b", [{"cid": "a", "title": "A"}], 1)
        st.update(active=["a"], verified_table_version=1, last_sync=9999999999)
        path = str(self._state(st))
        with patch.object(flow, "check", return_value={"ct": 60, "dur": 60, "prog": "4.5%"}), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "verify", return_value={"confirmed": False, "prog": "4.5%"}), \
             patch.object(flow, "restart_if_ended", return_value=True) as replay, \
             patch.object(monitor, "_outcome", return_value=False):
            self.assertEqual("running", monitor.run_one(self.driver, path))
            replay.assert_called_once()
        self.assertEqual([], state.load(path)["done"])
        self.assertEqual(["a"], state.load(path)["active"])

    def test_mcp_interval_and_desktop_workflow(self):
        from bangxue import mcp_server
        import inspect
        self.assertEqual(inspect.signature(mcp_server.bangxue_run).parameters["interval_min"].default, 1)
        self.assertEqual(cli.build_parser().parse_args(["run", "--max-seconds", "100"]).max_seconds, 100)

    def test_bridge_closes_only_the_owned_target(self):
        driver = WebBridgeDriver()
        tab = Tab("target", flow.play_url("a", "b"))
        driver._owned_urls[tab.id] = tab.url
        with patch.object(driver, "use", return_value=True), \
             patch.object(driver, "current_url", return_value=tab.url), \
             patch.object(driver, "_cmd", return_value={"data": {"result": True}}) as command:
            self.assertTrue(driver.close(tab))
        command.assert_called_once_with("cdp", {"method": "Target.closeTarget", "params": {"targetId": "target"}})
        self.assertNotIn("target", driver._owned_urls)


if __name__ == "__main__":
    unittest.main()
