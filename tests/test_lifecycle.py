import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from bangxue import classes, control, flow, monitor, runner, state
from bangxue.drivers.base import Tab


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.scope = self.directory / "scope.json"
        self.progress = self.directory / "_scope_state.json"
        self.path = self.directory / "a.json"
        self.driver = Mock(spec=["list_tabs", "close", "open", "eval"])
        self.messages = []
        self.log = self.messages.append
        self.select("a")

    def select(self, *ids):
        state.save(self.scope, {"classes": [{"wid": wid, "title": wid} for wid in ids]})

    def class_state(self, **changes):
        data = state.init_state("a", [{"cid": c, "title": c} for c in ("first", "next", "last")])
        data.update(changes)
        state.save(self.path, data)

    def cycle(self):
        return runner.run_cycle(self.driver, self.scope, self.directory, log=self.log)

    def test_captcha_mid_active_preserves_rest_and_stops_all_operations(self):
        self.class_state(active=["first", "next"], verified_table_version=1, last_sync=time.time(),
                         done_open=["old"])
        with patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "check", return_value={"stage": "blocked", "reason": "captcha"}) as check, \
             patch.object(flow, "close_owned") as close, patch.object(flow, "start") as start:
            self.assertEqual("paused", monitor.run_one(self.driver, self.path, self.log))
        self.assertEqual(["first", "next"], state.load(self.path)["active"])
        self.assertEqual(1, check.call_count)
        close.assert_not_called()
        start.assert_not_called()

    def test_captcha_after_resume_preserves_active(self):
        self.class_state(active=["first", "next"], verified_table_version=1, last_sync=time.time())
        with patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "check", side_effect=[{"ct": 4, "paused": True},
                                                      {"stage": "blocked", "reason": "login"}]), \
             patch.object(flow, "resume", return_value={}), patch.object(time, "sleep"), \
             patch.object(flow, "start") as start:
            self.assertEqual("paused", monitor.run_one(self.driver, self.path, self.log))
        self.assertEqual(["first", "next"], state.load(self.path)["active"])
        start.assert_not_called()

    def test_resume_selected_clears_both_states_preserves_other_class(self):
        self.class_state(paused_reason="captcha", failed={"first": "removed"})
        state.request_pause(self.path)
        state.save(self.progress, {"current": "a", "done": [], "skipped": {"a": "failed", "b": "removed"},
                                   "paused_reason": "captcha"})
        other = self.directory / "b.json"
        state.save(other, {"workshop": "b", "paused_reason": "login"})
        self.assertEqual("running", control.resume(self.scope, self.directory, log=self.log))
        self.assertFalse(state.pause_requested(self.path))
        self.assertNotIn("paused_reason", state.load(self.path))
        self.assertNotIn("paused_reason", state.load(self.progress))
        self.assertNotIn("failed", state.load(self.path))
        self.assertEqual({"b": "removed"}, state.load(self.progress)["skipped"])
        self.assertEqual("login", state.load(other)["paused_reason"])

    def test_stop_exact_owned_tab_preserves_duplicate_url_and_active(self):
        url = flow.play_url("first", "a")
        self.class_state(active=["first", "next"], owned_tabs=[{"id": "task", "url": url},
                                                                {"id": "changed", "url": url}])
        self.driver.list_tabs.return_value = [Tab("manual", url), Tab("task", url), Tab("changed", "about:blank")]
        self.driver.close.return_value = True
        self.assertEqual("paused", control.stop(self.driver, self.scope, self.directory, log=self.log))
        self.assertEqual(["task"], [call.args[0].id for call in self.driver.close.call_args_list])
        self.assertEqual("user", state.load(self.progress)["paused_reason"])
        st = state.load(self.path)
        self.assertEqual(["first", "next"], st["active"])
        self.assertEqual(["changed"], [r["id"] for r in st["owned_tabs"]])

    def test_scope_skipped_is_attention_and_old_current_ignored(self):
        state.save(self.progress, {"current": "former", "done": ["a", "former"],
                                   "skipped": {"former": "old"}})
        with patch.object(classes, "read_class_table", side_effect=RuntimeError("partial")) as read, \
             patch.object(monitor, "wait_interval") as wait:
            result = runner.run_loop(self.driver, self.scope, self.directory, log=self.log)
        self.assertEqual("attention", result)
        self.assertEqual(["a"], [call.args[1] for call in read.call_args_list])
        progress = state.load(self.progress)
        self.assertEqual([], progress["done"])
        self.assertEqual("partial", progress["skipped"]["a"])
        self.assertIsNone(progress["current"])
        wait.assert_not_called()
        self.assertIn("已完成 0/1", self.messages[-1])

    def test_current_manual_unmapped_and_removed_class_does_not_spin(self):
        self.class_state(courses=[{"cid": "manual", "manual": True}, {"cid": ""}, {"cid": "removed"}],
                         failed={"removed": "removed"})
        with patch.object(classes, "read_class_table", return_value=[{"title": "课", "prog": "0%"}]), \
             patch.object(flow, "sync_done", return_value=set()), patch.object(flow, "list_play_cids", return_value=[]):
            self.assertEqual("attention", self.cycle())
        self.assertIn("待人工 1 门，未映射 1 门，失败 1 门", state.load(self.progress)["skipped"]["a"])
        self.assertEqual("running", control.resume(self.scope, self.directory, log=self.log))
        self.assertTrue(state.load(self.path)["recapture"])

    def test_after_failed_class_other_selected_classes_are_checked(self):
        self.select("a", "b")
        with patch.object(classes, "read_class_table", side_effect=[[], [{"title": "ok", "prog": "100%"}]]), \
             patch.object(classes, "ensure_enrolled", return_value=False):
            self.assertEqual("attention", self.cycle())
        self.assertEqual(["b"], state.load(self.progress)["done"])
        self.assertEqual("报名未确认", state.load(self.progress)["skipped"]["a"])
        self.assertIn("已完成 1/2", self.messages[-1])

    def test_table_complete_exits_loop_immediately(self):
        with patch.object(classes, "read_class_table", return_value=[{"title": "ok", "prog": "100%"}]), \
             patch.object(monitor, "wait_interval") as wait:
            self.assertEqual("complete", runner.run_loop(self.driver, self.scope, self.directory, log=self.log))
        wait.assert_not_called()

    def test_stop_while_operation_in_progress_preserves_state_and_interrupts_browser(self):
        entered = threading.Event()
        proceed = threading.Event()
        self.class_state(active=["first"])
        self.driver.open.return_value = Tab("new", "https://example.invalid/mock")
        self.driver.list_tabs.return_value = [self.driver.open.return_value]
        self.driver.close.return_value = True

        def read(driver, wid):
            driver.open("https://example.invalid/mock", new_tab=True)
            entered.set()
            proceed.wait(3)
            driver.eval("next action")
            return []

        results = {}
        with patch.object(classes, "read_class_table", side_effect=read):
            running = threading.Thread(target=lambda: results.update(cycle=self.cycle()))
            running.start()
            self.assertTrue(entered.wait(2))
            stopping = threading.Thread(target=lambda: results.update(
                stop=control.stop(self.driver, self.scope, self.directory, log=self.log)))
            stopping.start()
            for _ in range(100):
                if state.pause_requested(self.progress):
                    break
                time.sleep(0.01)
            self.assertTrue(state.pause_requested(self.progress))
            proceed.set()
            running.join(3)
            stopping.join(3)
        self.assertEqual({"cycle": "paused", "stop": "paused"}, results)
        self.driver.eval.assert_not_called()
        self.assertEqual("new", self.driver.close.call_args.args[0].id)
        self.assertEqual("user", state.load(self.path)["paused_reason"])
        self.assertEqual(["first"], state.load(self.path)["active"])

    def test_process_lock_reports_contention_and_releases_after_close(self):
        code = (
            "from bangxue.state import acquire_lock; import sys; "
            "lock = acquire_lock(sys.argv[1]); print('acquired' if lock else 'busy')"
        )
        def probe():
            return subprocess.check_output([sys.executable, "-c", code, str(self.progress)],
                                           text=True, timeout=5).strip()
        with state.acquire_lock(self.progress):
            self.assertEqual("busy", probe())
        self.assertEqual("acquired", probe())

    def test_table_change_with_all_previous_ids_recaptures_on_retry(self):
        self.class_state(courses=[{"cid": "first", "title": "first"}])
        rows = [{"title": "new", "prog": "0%"}]
        with patch.object(classes, "read_class_table", return_value=rows), \
             patch.object(flow, "sync_done", side_effect=flow.CourseListChanged("旧清单已变化")):
            self.assertEqual("attention", self.cycle())
        self.assertTrue(state.load(self.path)["recapture"])
        self.assertEqual("running", control.resume(self.scope, self.directory, log=self.log))
        updated = [{"title": "new", "cid": "next"}]
        with patch.object(classes, "read_class_table", return_value=rows), \
             patch.object(flow, "capture", return_value={"courses": updated}) as capture, \
             patch.object(flow, "sync_done", return_value=set()), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "start", return_value={"ok": True}):
            self.assertEqual("running", self.cycle())
        capture.assert_called_once()
        self.assertEqual(["next"], state.load(self.path)["active"])

    def test_invalid_scope_is_rejected_before_reading_browser(self):
        self.select("../outside")
        self.assertEqual("attention", self.cycle())
        self.assertEqual([], self.driver.mock_calls)

    def test_no_repeated_start_for_unconfirmed_course(self):
        self.class_state(courses=[{"cid": "first", "title": "first"}])
        with patch.object(flow, "sync_done", return_value=set()), \
             patch.object(flow, "list_play_cids", return_value=[]), \
             patch.object(flow, "start", return_value={"stage": "entry_failed", "ok": False}) as start:
            self.assertEqual("attention", monitor.run_one(self.driver, self.path, self.log))
            self.assertEqual("attention", monitor.run_one(self.driver, self.path, self.log))
        self.assertEqual(1, start.call_count)


if __name__ == "__main__":
    unittest.main()
