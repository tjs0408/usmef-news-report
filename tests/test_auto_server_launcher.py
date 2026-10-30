"""Automatic launcher checks are fully mocked; no live server is touched."""

from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import start_web as launcher


ROOT = Path("C:/보고서 프로젝트")


def idle_state(pid=1234):
    return {
        "pid": pid,
        "styleVersion": "livestock-brief-v24",
        "articleBusy": False,
        "reportBusy": False,
        "busy": False,
    }


class AutomaticRestartSafetyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        self.identities = [{"pid": 1234, "role": "listener"}]
        self.inspect = patch.object(launcher, "inspect_server", return_value=self.identities).start()
        self.stop = patch.object(launcher, "stop_server").start()
        self.state = patch.object(launcher, "read_server_state", return_value=idle_state()).start()
        self.port = patch.object(launcher, "port_is_open", return_value=False).start()
        self.prompt = patch("builtins.input", side_effect=AssertionError("Automatic mode must never prompt")).start()
        self.sleep = patch.object(launcher.time, "sleep").start()

    def assert_preserved_without_prompt(self):
        self.prompt.assert_not_called()
        self.stop.assert_not_called()

    def test_verified_idle_server_restarts_without_any_input(self):
        self.assertTrue(launcher.restart_existing_server(ROOT, automatic=True))
        self.inspect.assert_called_once_with(ROOT, port=5002)
        self.stop.assert_called_once_with(ROOT, self.identities, port=5002)
        self.assertEqual(self.state.call_count, 2)
        self.prompt.assert_not_called()

    def test_running_article_or_report_blocks_automatic_restart(self):
        for field in ("articleBusy", "reportBusy"):
            with self.subTest(field=field):
                self.state.return_value = {**idle_state(), field: True, "busy": True}
                self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_unknown_legacy_or_unavailable_state_never_assumes_idle(self):
        self.state.return_value = None
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_wrong_http_pid_does_not_stop_verified_process(self):
        self.state.return_value = idle_state(pid=5678)
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_state_disappearing_before_stop_cancels_automatic_restart(self):
        self.state.side_effect = [idle_state(), None]
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_pid_changing_before_stop_cancels_automatic_restart(self):
        self.state.side_effect = [idle_state(), idle_state(pid=5678)]
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_new_job_before_stop_cancels_automatic_restart(self):
        self.state.side_effect = [idle_state(), {**idle_state(), "busy": True, "articleBusy": True}]
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_ownership_failure_does_not_query_or_stop_a_process(self):
        self.inspect.side_effect = launcher.ServerControlError("fixture other project")
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.state.assert_not_called()
        self.assert_preserved_without_prompt()

    def test_disappeared_listener_is_not_replaced_without_reinspection(self):
        self.inspect.return_value = []
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.assert_preserved_without_prompt()

    def test_stop_failure_is_not_reported_as_success(self):
        self.stop.side_effect = launcher.ServerControlError("fixture process changed")
        self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.stop.assert_called_once_with(ROOT, self.identities, port=5002)
        self.prompt.assert_not_called()

    def test_port_remaining_busy_prevents_duplicate_start(self):
        self.port.return_value = True
        with patch.object(launcher.time, "monotonic", side_effect=[100, 111]):
            self.assertFalse(launcher.restart_existing_server(ROOT, automatic=True))
        self.prompt.assert_not_called()


class AutomaticLauncherRoutingTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        patch.object(Path, "is_file", return_value=True).start()
        self.port = patch.object(launcher, "port_is_open", return_value=True).start()
        self.page = patch.object(launcher, "is_project_page", return_value=True).start()
        patch.object(launcher, "read_server_state", return_value=idle_state()).start()
        self.restart = patch.object(launcher, "restart_existing_server", return_value=True).start()
        self.browser = patch.object(launcher, "open_page").start()
        self.prompt = patch("builtins.input", side_effect=AssertionError("Unexpected interactive prompt")).start()
        self.spawn = patch.object(launcher.subprocess, "Popen").start()
        self.process = self.spawn.return_value
        self.process.poll.return_value = None
        self.process.wait.return_value = 0

    def test_automatic_flag_is_forwarded_to_verified_restart(self):
        self.assertEqual(launcher.run(ROOT, restart_existing=True, automatic_restart=True), 0)
        self.restart.assert_called_once_with(ROOT, automatic=True)
        self.spawn.assert_called_once()
        self.browser.assert_called_once_with()
        self.prompt.assert_not_called()

    def test_absent_server_starts_directly_without_restart_or_prompt(self):
        self.port.return_value = False
        self.assertEqual(launcher.run(ROOT, restart_existing=True, automatic_restart=True), 0)
        self.restart.assert_not_called()
        self.spawn.assert_called_once()
        self.browser.assert_called_once_with()
        self.prompt.assert_not_called()

    def test_rejected_automatic_restart_does_not_launch_a_second_server(self):
        self.restart.return_value = False
        self.assertEqual(launcher.run(ROOT, restart_existing=True, automatic_restart=True), 1)
        self.spawn.assert_not_called()
        self.browser.assert_not_called()
        self.prompt.assert_not_called()

    def test_other_application_on_port_is_not_restarted(self):
        self.page.return_value = False
        self.assertEqual(launcher.run(ROOT, restart_existing=True, automatic_restart=True), 1)
        self.restart.assert_not_called()
        self.spawn.assert_not_called()
        self.browser.assert_not_called()
        self.prompt.assert_not_called()

    def test_batch_opts_into_scoped_no_prompt_restart(self):
        batch = (launcher.PROJECT_ROOT / "서버실행.bat").read_text(encoding="utf-8")
        self.assertIn('"scripts\\start_web.py" --restart --yes', batch)


if __name__ == "__main__":
    unittest.main()
