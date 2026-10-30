"""No real process inspection or termination: every PowerShell call is mocked."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import project_server_control as control


ROOT = Path("C:/보고서 프로젝트")
VENV = str(ROOT / ".venv/Scripts/python.exe")
BASE = "C:/Python/python.exe"
STAMP = "2026-10-23T00:00:00.1234567Z"


def identity(pid=200, parent=100, exe=BASE, script="app.py", stamp=STAMP):
    return {
        "pid": pid, "parentPid": parent, "creationTime": stamp,
        "executablePath": exe,
        "commandLine": f'"{exe}" -X utf8 "{script}"',
    }


def legacy():
    return {"listeners": [identity()], "parents": [identity(pid=100, parent=50, exe=VENV)]}


def response(payload=None, returncode=0, stdout=None):
    if stdout is None:
        stdout = json.dumps(payload if payload is not None else legacy(), ensure_ascii=False)
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="private diagnostics should not be repeated")


class ServerIdentityTests(unittest.TestCase):
    def inspect(self, payload):
        with patch.object(control.subprocess, "run", return_value=response(payload)) as run:
            verified = control.inspect_server(ROOT)
        return verified, run

    def test_legacy_venv_parent_proves_project_for_bundled_python_child(self):
        verified, run = self.inspect(legacy())
        self.assertEqual([item["pid"] for item in verified], [200, 100])
        self.assertEqual([item["role"] for item in verified], ["listener", "wrapper"])
        self.assertEqual(verified[0]["creationTime"], STAMP)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertNotIn("ExecutionPolicy", command[-1])
        self.assertNotIn("Stop-Process", command[-1])
        self.assertEqual(run.call_args.kwargs["env"]["BRIEF_CONTROL_PORT"], "5002")

    def test_new_absolute_app_path_with_spaces_and_korean(self):
        payload = legacy()
        for item in payload["listeners"] + payload["parents"]:
            item["commandLine"] = f'"{item["executablePath"]}" -X utf8 "{ROOT / "app.py"}"'
        verified, _ = self.inspect(payload)
        self.assertEqual(len(verified), 2)

    def test_direct_project_venv_listener_does_not_include_console_parent(self):
        payload = {"listeners": [identity(exe=VENV)], "parents": [identity(pid=100, parent=50, exe="C:/Windows/cmd.exe", script="ignored")]}
        verified, _ = self.inspect(payload)
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["pid"], 200)

    def test_no_listener_means_no_process_to_stop(self):
        verified, _ = self.inspect({"listeners": [], "parents": []})
        self.assertEqual(verified, [])

    def test_duplicate_ipv4_ipv6_is_expected_to_be_deduplicated_by_query(self):
        self.assertIn("Select-Object -ExpandProperty OwningProcess -Unique", control._INSPECT_SCRIPT)

    def test_foreign_project_is_rejected_even_with_same_app_filename(self):
        payload = legacy()
        payload["parents"][0] = identity(pid=100, parent=50, exe="C:/Other/.venv/Scripts/python.exe")
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_reused_parent_pid_with_newer_project_process_is_not_stopped(self):
        payload = legacy()
        payload["parents"][0]["creationTime"] = "2026-10-23T01:00:00Z"
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_impossible_creation_date_is_not_an_identity(self):
        payload = legacy()
        payload["listeners"][0]["creationTime"] = "2026-99-23T00:00:00Z"
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_foreign_absolute_script_is_rejected_with_project_venv(self):
        payload = legacy()
        payload["listeners"][0] = identity(script="C:/Other/app.py")
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_command_line_executable_must_match_the_actual_executable(self):
        payload = legacy()
        payload["listeners"][0]["commandLine"] = '"C:/Other/python.exe" -X utf8 app.py'
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_launcher_and_unrelated_python_commands_cannot_be_stopped(self):
        for script in ("scripts/start_web.py", "manage.py", "-c", "app.py --dangerous-option"):
            with self.subTest(script=script), self.assertRaises(control.ServerControlError):
                payload = legacy()
                payload["listeners"][0] = identity(script=script)
                self.inspect(payload)

    def test_extra_python_arguments_are_rejected(self):
        payload = legacy()
        payload["listeners"][0]["commandLine"] += " --port 5002"
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_multiple_listeners_are_ambiguous_and_rejected(self):
        payload = legacy()
        payload["listeners"].append(identity(pid=300, parent=100))
        with self.assertRaises(control.ServerControlError):
            self.inspect(payload)

    def test_invalid_ids_missing_fields_and_creation_times_fail_closed(self):
        changes = ({"pid": 0}, {"pid": True}, {"parentPid": 0}, {"parentPid": 200}, {"creationTime": "yesterday"}, {"executablePath": "python.exe"}, {"commandLine": ""}, {"commandLine": "app.py\nStop-Process"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(control.ServerControlError):
                payload = legacy()
                payload["listeners"][0].update(change)
                self.inspect(payload)

    def test_invalid_payload_and_json_fail_closed(self):
        for payload in ([], None, {"listeners": "bad", "parents": []}, {"listeners": [], "parents": None}):
            with self.subTest(payload=payload), patch.object(control.subprocess, "run", return_value=response(stdout=json.dumps(payload))), self.assertRaises(control.ServerControlError):
                control.inspect_server(ROOT)
        with patch.object(control.subprocess, "run", return_value=response(stdout="not json")), self.assertRaises(control.ServerControlError):
            control.inspect_server(ROOT)

    def test_windows_paths_are_case_and_slash_normalized(self):
        payload = legacy()
        payload["parents"][0]["executablePath"] = VENV.upper().replace("/", "\\")
        payload["parents"][0]["commandLine"] = f'"{VENV}" -X utf8 app.py'
        verified, _ = self.inspect(payload)
        self.assertEqual(len(verified), 2)


class StopServerTests(unittest.TestCase):
    def setUp(self):
        self.identities = control._verify_snapshot(ROOT, legacy()["listeners"], legacy()["parents"])

    def test_stop_only_sends_exact_verified_identities_after_second_inspection(self):
        with patch.object(control.subprocess, "run", side_effect=[response(), response(stdout="")]) as run:
            control.stop_server(ROOT, self.identities)
        self.assertEqual(run.call_count, 2)
        stop = run.call_args
        self.assertEqual(json.loads(stop.kwargs["env"]["BRIEF_CONTROL_IDENTITIES"]), self.identities)
        script = stop.args[0][-1]
        self.assertIn("Stop-Process -Id ([int]$expected.pid)", script)
        self.assertLess(script.index("foreach ($expected in $expectedItems)"), script.index("Stop-Process"))
        for field in ("creationTime", "executablePath", "commandLine", "parentPid"):
            self.assertIn(field, script)
        self.assertIn("Port ownership changed", script)
        self.assertNotIn("-Force", script)
        self.assertNotIn("taskkill", script.lower())
        self.assertNotIn("ExecutionPolicy", script)

    def test_pid_reused_by_foreign_program_is_never_stopped(self):
        current = legacy()
        current["listeners"][0] = identity(exe="C:/Windows/notepad.exe")
        with patch.object(control.subprocess, "run", return_value=response(current)) as run, self.assertRaises(control.ServerControlError):
            control.stop_server(ROOT, self.identities)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("Stop-Process", run.call_args.args[0][-1])

    def test_same_pid_with_changed_creation_time_is_never_stopped(self):
        current = legacy()
        current["listeners"][0]["creationTime"] = "2026-10-23T00:01:00.1234567Z"
        with patch.object(control.subprocess, "run", return_value=response(current)) as run, self.assertRaises(control.ServerControlError):
            control.stop_server(ROOT, self.identities)
        self.assertEqual(run.call_count, 1)

    def test_changed_port_owner_and_already_stopped_server_cancel(self):
        for payload in ({"listeners": [], "parents": []}, {"listeners": [identity(pid=300)], "parents": legacy()["parents"]}):
            with self.subTest(payload=payload), patch.object(control.subprocess, "run", return_value=response(payload)) as run, self.assertRaises(control.ServerControlError):
                control.stop_server(ROOT, self.identities)
            self.assertEqual(run.call_count, 1)

    def test_tampered_extra_process_and_wrong_role_fail_before_commands(self):
        invalid = [[], self.identities + [dict(self.identities[0], pid=999)], [dict(self.identities[0], role="wrapper")], [dict(self.identities[0], creationTime="bad")], [dict(self.identities[0], extra="do not permit unvalidated fields"), self.identities[1]]]
        for identities in invalid:
            with self.subTest(identities=identities), patch.object(control.subprocess, "run") as run, self.assertRaises(control.ServerControlError):
                control.stop_server(ROOT, identities)
            run.assert_not_called()

    def test_revalidation_error_does_not_try_another_termination_method(self):
        with patch.object(control.subprocess, "run", side_effect=[response(), response(returncode=1)]) as run, self.assertRaises(control.ServerControlError) as raised:
            control.stop_server(ROOT, self.identities)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("private diagnostics", str(raised.exception))

    def test_empty_stop_and_invalid_port_are_rejected(self):
        for port in (0, 65536, True, "5002"):
            with self.subTest(port=port), patch.object(control.subprocess, "run") as run, self.assertRaises(control.ServerControlError):
                control.inspect_server(ROOT, port=port)
            run.assert_not_called()
        with self.assertRaises(control.ServerControlError):
            control.stop_server(ROOT, [])

    def test_process_query_errors_do_not_leak_raw_diagnostics(self):
        for error in (OSError("private"), subprocess.TimeoutExpired("powershell", 20)):
            with self.subTest(error=error), patch.object(control.subprocess, "run", side_effect=error), self.assertRaises(control.ServerControlError) as raised:
                control.inspect_server(ROOT)
            self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
