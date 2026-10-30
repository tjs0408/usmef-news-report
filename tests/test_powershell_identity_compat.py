"""Exercise only JSON fixture decoding in Windows PowerShell, never processes.

No process IDs below identify real processes. The executable paths and command
lines are inert JSON strings; the production inspection/stop scripts never run.
"""

import json
import os
import shutil
import subprocess
import unittest

from scripts import project_server_control as control


POWERSHELL = shutil.which("powershell.exe") if os.name == "nt" else None
PROHIBITED_OPERATIONS = (
    "Get-CimInstance", "Get-NetTCPConnection", "Get-Process", "Stop-Process",
    "Start-Process", "taskkill", "Read-Identity", "Read-Listeners",
)


def fixture_decode_fragment() -> str:
    """Take only the production JSON assignment(s), not a stop-script prelude."""
    lines = control._STOP_SCRIPT.splitlines()
    start = next(index for index, line in enumerate(lines)
                 if "BRIEF_CONTROL_IDENTITIES" in line and "ConvertFrom-Json" in line)
    end = next(index for index in range(start + 1, len(lines))
               if lines[index].lstrip().startswith("$portNumber ="))
    fragment = "\n".join(lines[start:end])
    for operation in PROHIBITED_OPERATIONS:
        if operation.casefold() in fragment.casefold():
            raise AssertionError(f"Process operation is forbidden in a JSON fixture: {operation}")
    return fragment


def identity(pid, parent_pid, role, *, prefix="C:/FixtureProject"):
    executable = prefix + "/.venv/Scripts/python.exe"
    return {
        "pid": pid,
        "parentPid": parent_pid,
        "creationTime": "2026-10-23T00:00:00.1234567Z",
        "executablePath": executable,
        "commandLine": f'"{executable}" -X utf8 "{prefix}/app.py"',
        "role": role,
    }


@unittest.skipUnless(POWERSHELL, "Windows powershell.exe is required for pure JSON compatibility fixtures")
class PowerShellIdentityJsonCompatibilityTests(unittest.TestCase):
    def decode(self, identities):
        # No module helper is invoked: _run, inspect_server, stop_server, and
        # every production PowerShell process operation remain unused.
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
""" + fixture_decode_fragment() + r"""
$fixtureListener = @($expectedItems | Where-Object { $_.role -eq 'listener' })
if ($fixtureListener.Count -ne 1) { throw 'JSON fixture did not produce one listener.' }
[pscustomobject]@{
    count = [int]$expectedItems.Count
    itemTypes = @($expectedItems | ForEach-Object { $_.GetType().FullName })
    pids = @($expectedItems | ForEach-Object { [int]$_.pid })
    roles = @($expectedItems | ForEach-Object { [string]$_.role })
    paths = @($expectedItems | ForEach-Object { [string]$_.executablePath })
    commandLines = @($expectedItems | ForEach-Object { [string]$_.commandLine })
    creationTimes = @($expectedItems | ForEach-Object { [string]$_.creationTime })
    listenerCount = [int]$fixtureListener.Count
    listenerPid = [int]$fixtureListener[0].pid
} | ConvertTo-Json -Depth 5 -Compress
"""
        for operation in PROHIBITED_OPERATIONS:
            self.assertNotIn(operation.casefold(), script.casefold())
        environment = os.environ.copy()
        environment["BRIEF_CONTROL_IDENTITIES"] = json.dumps(identities, ensure_ascii=False)
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment, capture_output=True, text=True, encoding="utf-8",
            errors="strict", timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        decoded = json.loads(result.stdout)
        self.assertEqual(decoded["count"], len(identities))
        self.assertEqual(decoded["itemTypes"], ["System.Management.Automation.PSCustomObject"] * len(identities))
        self.assertEqual(decoded["pids"], [item["pid"] for item in identities])
        self.assertEqual(decoded["roles"], [item["role"] for item in identities])
        self.assertEqual(decoded["listenerCount"], 1)
        self.assertEqual(decoded["listenerPid"], identities[0]["pid"])
        self.assertEqual(decoded["creationTimes"], [item["creationTime"] for item in identities])
        return decoded

    def test_single_identity_is_a_flat_object_with_scalar_pid(self):
        self.decode([identity(910001, 910000, "listener")])

    def test_two_identities_are_flat_and_listener_pid_is_not_an_array(self):
        self.decode([
            identity(910002, 910001, "listener"),
            identity(910001, 910000, "wrapper"),
        ])

    def test_unicode_paths_and_quoted_commands_round_trip_via_environment(self):
        fixtures = [
            identity(910002, 910001, "listener", prefix="C:/가상 보고서 프로젝트"),
            identity(910001, 910000, "wrapper", prefix="C:/가상 보고서 프로젝트"),
        ]
        decoded = self.decode(fixtures)
        self.assertEqual(decoded["paths"], [item["executablePath"] for item in fixtures])
        self.assertEqual(decoded["commandLines"], [item["commandLine"] for item in fixtures])


if __name__ == "__main__":
    unittest.main()
