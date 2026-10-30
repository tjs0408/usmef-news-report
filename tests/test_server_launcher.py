"""Launcher tests use mocks: they never start/stop a server or open a browser."""

from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from scripts import start_web as launcher


class ServerLauncherTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("C:/보고서 프로젝트")
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        self.files = patch.object(Path, "is_file", return_value=True).start()
        self.port = patch.object(launcher, "port_is_open", return_value=False).start()
        self.page = patch.object(launcher, "is_project_page", return_value=True).start()
        self.state = patch.object(launcher, "read_server_state", return_value=None).start()
        self.browser = patch.object(launcher, "open_page").start()
        self.restart = patch.object(launcher, "restart_existing_server", return_value=True).start()
        self.spawn = patch.object(launcher.subprocess, "Popen").start()
        self.process = self.spawn.return_value
        self.process.poll.return_value = None
        self.process.wait.return_value = 0

    def test_missing_environment_does_not_start_or_probe(self):
        self.files.return_value = False
        self.assertEqual(launcher.run(self.root), 1)
        self.port.assert_not_called()
        self.spawn.assert_not_called()
        self.browser.assert_not_called()

    def test_existing_project_opens_browser_without_spawning_or_stopping(self):
        self.port.return_value = True
        self.assertEqual(launcher.run(self.root), 0)
        self.browser.assert_called_once_with()
        self.spawn.assert_not_called()

    def test_unrelated_or_unresponsive_port_is_left_alone(self):
        self.port.return_value = True
        self.page.return_value = False
        self.assertEqual(launcher.run(self.root), 1)
        self.spawn.assert_not_called()
        self.browser.assert_not_called()

    def test_restart_mode_restarts_verified_server_before_starting_new_process(self):
        self.port.return_value = True
        self.assertEqual(launcher.run(self.root, restart_existing=True), 0)
        self.restart.assert_called_once_with(self.root, automatic=False)
        self.spawn.assert_called_once()
        self.browser.assert_called_once_with()

    def test_failed_or_cancelled_restart_never_starts_another_server(self):
        self.port.return_value = True
        self.restart.return_value = False
        self.assertEqual(launcher.run(self.root, restart_existing=True), 1)
        self.spawn.assert_not_called()
        self.browser.assert_not_called()

    def test_start_uses_project_venv_and_cwd_with_explicit_port(self):
        with patch.dict(launcher.os.environ, {"PORT": "9999", "LAUNCH_TEST_VALUE": "preserved"}):
            self.assertEqual(launcher.run(self.root), 0)
        command = self.spawn.call_args.args[0]
        options = self.spawn.call_args.kwargs
        self.assertEqual(command, [str(self.root / ".venv/Scripts/python.exe"), "-X", "utf8", str(self.root / "app.py")])
        self.assertEqual(options["cwd"], str(self.root))
        self.assertEqual(options["env"]["PORT"], "5002")
        self.assertEqual(options["env"]["PYTHONUTF8"], "1")
        self.assertEqual(options["env"]["LAUNCH_TEST_VALUE"], "preserved")
        self.assertNotIn("shell", options)
        self.browser.assert_called_once_with()

    def test_browser_waits_for_http_readiness(self):
        self.page.side_effect = [False, True]
        with patch.object(launcher.time, "monotonic", side_effect=[100, 100.1]), patch.object(launcher.time, "sleep") as sleep:
            self.assertEqual(launcher.run(self.root), 0)
        self.assertEqual(self.page.call_count, 2)
        sleep.assert_called_once_with(0.25)
        self.browser.assert_called_once_with()

    def test_slow_start_keeps_foreground_server_without_opening_prematurely(self):
        self.page.return_value = False
        with patch.object(launcher.time, "monotonic", side_effect=[100, 131]):
            self.assertEqual(launcher.run(self.root), 0)
        self.browser.assert_not_called()
        self.process.wait.assert_called_once_with()
        self.process.kill.assert_not_called()
        self.process.terminate.assert_not_called()

    def test_server_startup_error_is_preserved(self):
        self.process.poll.return_value = 1
        self.process.wait.return_value = 1
        self.assertEqual(launcher.run(self.root), 1)
        self.page.assert_not_called()
        self.browser.assert_not_called()

    def test_subprocess_os_error_is_reported_without_browser(self):
        self.spawn.side_effect = OSError("test launch failure")
        self.assertEqual(launcher.run(self.root), 1)
        self.browser.assert_not_called()

    def test_ctrl_c_waits_for_child_without_forced_termination(self):
        self.process.poll.side_effect = KeyboardInterrupt
        self.assertEqual(launcher.run(self.root), 0)
        self.process.wait.assert_called_once_with(timeout=8)
        self.process.kill.assert_not_called()
        self.process.terminate.assert_not_called()

    def test_ctrl_c_timeout_does_not_force_kill(self):
        self.process.poll.side_effect = KeyboardInterrupt
        self.process.wait.side_effect = subprocess.TimeoutExpired("app.py", 8)
        self.assertEqual(launcher.run(self.root), 130)
        self.process.kill.assert_not_called()
        self.process.terminate.assert_not_called()


class LauncherProbeTests(unittest.TestCase):
    def response(self, page, status=200, url=launcher.SERVER_URL):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.geturl.return_value = url
        response.read.return_value = page.encode("utf-8")
        return response

    def test_probe_requires_both_project_markers(self):
        for body, expected in ((" ".join(launcher.PAGE_MARKERS), True), (launcher.PAGE_MARKERS[0], False), ("other server", False)):
            with self.subTest(body=body), patch.object(launcher, "build_opener") as opener:
                opener.return_value.open.return_value = self.response(body)
                self.assertEqual(launcher.is_project_page(), expected)
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, launcher.SERVER_URL)

    def test_non_ok_foreign_url_and_connection_failures_are_not_ready(self):
        for status, url in ((503, launcher.SERVER_URL), (200, "https://example.invalid/")):
            with self.subTest(status=status, url=url), patch.object(launcher, "build_opener") as opener:
                opener.return_value.open.return_value = self.response(" ".join(launcher.PAGE_MARKERS), status=status, url=url)
                self.assertFalse(launcher.is_project_page())
        with patch.object(launcher, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("test unavailable")
            self.assertFalse(launcher.is_project_page())

    def test_redirects_are_not_followed(self):
        self.assertIsNone(launcher.NoRedirects().redirect_request(None, None, 302, "found", {}, "https://example.invalid/"))

    def test_port_probe_handles_open_and_closed_connections(self):
        with patch.object(launcher.socket, "create_connection") as connection:
            self.assertTrue(launcher.port_is_open())
            connection.assert_called_once_with(("127.0.0.1", 5002), timeout=0.5)
            connection.side_effect = OSError("test closed")
            self.assertFalse(launcher.port_is_open())

    def test_browser_failure_preserves_manual_url_message(self):
        for outcome in (False, OSError("test browser unavailable")):
            with self.subTest(outcome=outcome), patch.object(launcher.webbrowser, "open") as browser, patch("builtins.print") as message:
                if isinstance(outcome, Exception):
                    browser.side_effect = outcome
                else:
                    browser.return_value = outcome
                launcher.open_page()
                browser.assert_called_once_with(launcher.SERVER_URL, new=2)
                self.assertIn(launcher.SERVER_URL, message.call_args.args[0])

    def test_launcher_markers_match_the_real_template(self):
        template = (launcher.PROJECT_ROOT / "templates/index.html").read_text(encoding="utf-8")
        for marker in launcher.PAGE_MARKERS:
            self.assertIn(marker, template)

    def test_batch_uses_own_directory_and_confirmed_restart_helper_without_security_changes(self):
        batch = (launcher.PROJECT_ROOT / "서버실행.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', batch)
        self.assertIn('".venv\\Scripts\\python.exe" -X utf8 "scripts\\start_web.py"', batch)
        self.assertIn('"scripts\\start_web.py" --restart --yes', batch)
        self.assertIn("pause", batch)
        for unsafe in ("Stop-Process", "taskkill", "ExecutionPolicy", "reg add"):
            self.assertNotIn(unsafe, batch)


class RestartConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        self.root = Path("C:/보고서 프로젝트")
        self.identities = [{"pid": 1234, "role": "listener"}]
        self.inspect = patch.object(launcher, "inspect_server", return_value=self.identities).start()
        self.stop = patch.object(launcher, "stop_server").start()
        self.port = patch.object(launcher, "port_is_open", return_value=False).start()
        self.state = patch.object(launcher, "read_server_state", return_value=None).start()
        self.confirm = patch("builtins.input", return_value="Y").start()

    @staticmethod
    def idle(pid=1234):
        return {"pid": pid, "busy": False, "articleBusy": False, "reportBusy": False, "styleVersion": "livestock-brief-v24"}

    def test_legacy_server_needs_human_confirmation_before_exact_stop(self):
        self.assertTrue(launcher.restart_existing_server(self.root))
        self.confirm.assert_called_once()
        self.stop.assert_called_once_with(self.root, self.identities, port=5002)
        self.assertEqual(self.state.call_count, 2)

    def test_cancel_preserves_existing_server(self):
        for answer in ("", "n", "no"):
            with self.subTest(answer=answer):
                self.confirm.return_value = answer
                self.assertFalse(launcher.restart_existing_server(self.root))
        self.stop.assert_not_called()

    def test_interrupt_or_no_interactive_console_cancels(self):
        for error in (EOFError(), KeyboardInterrupt()):
            with self.subTest(error=error):
                self.confirm.side_effect = error
                self.assertFalse(launcher.restart_existing_server(self.root))
        self.stop.assert_not_called()

    def test_busy_server_is_not_prompted_or_stopped(self):
        self.state.return_value = {**self.idle(), "busy": True, "articleBusy": True}
        self.assertFalse(launcher.restart_existing_server(self.root))
        self.confirm.assert_not_called()
        self.stop.assert_not_called()

    def test_changed_http_process_is_not_stopped(self):
        self.state.return_value = self.idle(pid=9876)
        self.assertFalse(launcher.restart_existing_server(self.root))
        self.stop.assert_not_called()

    def test_new_job_during_prompt_is_not_stopped(self):
        self.state.side_effect = [self.idle(), {**self.idle(), "busy": True, "reportBusy": True}]
        self.assertFalse(launcher.restart_existing_server(self.root))
        self.stop.assert_not_called()

    def test_lost_state_after_known_idle_is_not_stopped(self):
        self.state.side_effect = [self.idle(), None]
        self.assertFalse(launcher.restart_existing_server(self.root))
        self.stop.assert_not_called()

    def test_identity_failure_is_not_stopped(self):
        self.inspect.side_effect = launcher.ServerControlError("test different project")
        self.assertFalse(launcher.restart_existing_server(self.root))
        self.confirm.assert_not_called()
        self.stop.assert_not_called()

    def test_stop_failure_cannot_claim_restart_success(self):
        self.stop.side_effect = launcher.ServerControlError("test changed process")
        self.assertFalse(launcher.restart_existing_server(self.root))

    def test_busy_port_after_stop_cannot_start_duplicate(self):
        self.port.return_value = True
        with patch.object(launcher.time, "monotonic", side_effect=[100, 111]):
            self.assertFalse(launcher.restart_existing_server(self.root))


class ServerStateProbeTests(unittest.TestCase):
    def state_response(self, state):
        import json
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.geturl.return_value = launcher.STATE_URL
        response.read.return_value = json.dumps(state).encode("utf-8")
        return response

    def test_valid_loopback_server_state(self):
        state = RestartConfirmationTests.idle()
        with patch.object(launcher, "build_opener") as opener:
            opener.return_value.open.return_value = self.state_response(state)
            self.assertEqual(launcher.read_server_state(), state)
            self.assertEqual(opener.return_value.open.call_args.args[0].full_url, launcher.STATE_URL)

    def test_wrong_fields_are_not_trusted_as_idle(self):
        idle = RestartConfirmationTests.idle()
        for state in ([], {}, {**idle, "busy": "false"}, {**idle, "pid": True}, {**idle, "busy": True}):
            with self.subTest(state=state), patch.object(launcher, "build_opener") as opener:
                opener.return_value.open.return_value = self.state_response(state)
                self.assertIsNone(launcher.read_server_state())

    def test_unavailable_legacy_endpoint_is_unknown_not_idle(self):
        with patch.object(launcher, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("legacy endpoint unavailable")
            self.assertIsNone(launcher.read_server_state())


if __name__ == "__main__":
    unittest.main()
