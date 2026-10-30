"""Narrow process control for the user's interactive Windows server launcher.

Only the project-owned ``app.py`` listener and its venv ``app.py`` wrapper can
be returned or stopped. Callers require user authorization and must check jobs
before an explicitly selected automatic restart.
This module is not an agent-side substitute for an execution-policy denial.
"""

from __future__ import annotations

import json
from datetime import datetime
import ntpath
import os
from pathlib import Path
import re
import subprocess
from typing import Any


class ServerControlError(RuntimeError):
    """Identity could not be proved; leave all unrelated processes alone."""


_COMMAND = re.compile(
    r'^\s*(?:"(?P<quoted_exe>[^"\r\n]+)"|(?P<exe>[^\s"\r\n]+))'
    r'\s+(?:-X\s+utf8\s+)?(?:"(?P<quoted_script>[^"\r\n]+)"|(?P<script>[^\s"\r\n]+))\s*$',
    re.IGNORECASE,
)

_POWERSHELL_COMMON = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Read-Identity([int]$identityPid) {
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $identityPid)
    if ($null -eq $process) { return $null }
    return [pscustomobject]@{
        pid = [int]$process.ProcessId
        parentPid = [int]$process.ParentProcessId
        creationTime = $process.CreationDate.ToUniversalTime().ToString('o')
        executablePath = [string]$process.ExecutablePath
        commandLine = [string]$process.CommandLine
    }
}
function Read-Listeners([int]$serverPort) {
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -eq $serverPort } |
        Select-Object -ExpandProperty OwningProcess -Unique)
}
"""

_INSPECT_SCRIPT = _POWERSHELL_COMMON + r"""
$portNumber = [int]$env:BRIEF_CONTROL_PORT
$listeners = @()
$parents = @()
foreach ($listenerPid in @(Read-Listeners $portNumber)) {
    $listener = Read-Identity ([int]$listenerPid)
    if ($null -eq $listener) { throw 'Listener identity disappeared.' }
    $listeners += $listener
    $parent = Read-Identity ([int]$listener.parentPid)
    if ($null -ne $parent) { $parents += $parent }
}
[pscustomobject]@{ listeners = @($listeners); parents = @($parents) } | ConvertTo-Json -Depth 4 -Compress
"""

_STOP_SCRIPT = _POWERSHELL_COMMON + r"""
function Assert-SameIdentity($actual, $expected) {
    if ($null -eq $actual) { throw 'Project process disappeared; restart cancelled.' }
    foreach ($field in @('pid', 'parentPid', 'creationTime', 'executablePath', 'commandLine')) {
        if ([string]$actual.$field -cne [string]$expected.$field) {
            throw ('Process identity changed: ' + $field + '; restart cancelled.')
        }
    }
}
# Windows PowerShell 5.1 emits a JSON array as one pipeline object. Capture it
# first, then enumerate that value so each item is a process, not a nested array.
$decodedItems = $env:BRIEF_CONTROL_IDENTITIES | ConvertFrom-Json
$expectedItems = @($decodedItems)
$portNumber = [int]$env:BRIEF_CONTROL_PORT
if ($expectedItems.Count -lt 1 -or $expectedItems.Count -gt 2) { throw 'Invalid process identity count.' }
$expectedListener = @($expectedItems | Where-Object { $_.role -eq 'listener' })
if ($expectedListener.Count -ne 1) { throw 'Invalid listener identity.' }
foreach ($expected in $expectedItems) {
    Assert-SameIdentity (Read-Identity ([int]$expected.pid)) $expected
}
$currentListeners = @(Read-Listeners $portNumber)
if ($currentListeners.Count -ne 1 -or [int]$currentListeners[0] -ne [int]$expectedListener[0].pid) {
    throw 'Port ownership changed; restart cancelled.'
}
# All identities and the port were checked before the first stop. Re-read each
# identity immediately before stopping that exact PID; never kill a process tree.
foreach ($expected in $expectedItems) {
    $current = Read-Identity ([int]$expected.pid)
    if ($null -eq $current -and $expected.role -eq 'wrapper') { continue }
    Assert-SameIdentity $current $expected
    if ($expected.role -eq 'listener') {
        $currentListeners = @(Read-Listeners $portNumber)
        if ($currentListeners.Count -ne 1 -or [int]$currentListeners[0] -ne [int]$expected.pid) {
            throw 'Port ownership changed; restart cancelled.'
        }
    }
    Stop-Process -Id ([int]$expected.pid) -ErrorAction Stop
}
"""


def _windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value))


def _identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ServerControlError("서버 프로세스 정보를 확인하지 못했습니다.")
    result = {}
    for name in ("pid", "parentPid"):
        item = value.get(name)
        if type(item) is not int or item <= 0 or item > 2**32 - 1:
            raise ServerControlError("서버 프로세스 번호가 올바르지 않습니다.")
        result[name] = item
    if result["pid"] == result["parentPid"]:
        raise ServerControlError("서버 프로세스 관계가 올바르지 않습니다.")
    for name in ("creationTime", "executablePath", "commandLine"):
        item = value.get(name)
        if not isinstance(item, str) or not item or any(character in item for character in "\x00\r\n"):
            raise ServerControlError("서버 실행 경로와 시작 시간을 확인하지 못했습니다.")
        result[name] = item
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", result["creationTime"]):
        raise ServerControlError("서버 시작 시간을 확인하지 못했습니다.")
    try:
        datetime.fromisoformat(result["creationTime"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ServerControlError("서버 시작 시간이 올바르지 않습니다.") from error
    if not ntpath.isabs(result["executablePath"]):
        raise ServerControlError("서버 실행 경로가 올바르지 않습니다.")
    return result


def _application_command(identity: dict[str, Any], project_root: Path) -> bool:
    match = _COMMAND.fullmatch(identity["commandLine"])
    if not match:
        return False
    command_exe = match.group("quoted_exe") or match.group("exe")
    script = match.group("quoted_script") or match.group("script")
    return (
        _windows_path(command_exe) == _windows_path(identity["executablePath"])
        and ntpath.basename(identity["executablePath"]).lower() == "python.exe"
        and _windows_path(script) in {"app.py", _windows_path(str(project_root / "app.py"))}
    )


def _verify_snapshot(project_root: Path, listeners: Any, parents: Any) -> list[dict[str, Any]]:
    if not isinstance(listeners, list) or not isinstance(parents, list):
        raise ServerControlError("서버 프로세스 목록을 확인하지 못했습니다.")
    if not listeners:
        return []
    if len(listeners) != 1:
        raise ServerControlError("5002번 포트의 서버를 하나로 확인하지 못해 종료하지 않았습니다.")
    listener = _identity(listeners[0])
    if not _application_command(listener, project_root):
        raise ServerControlError("이 프로젝트의 app.py 서버인지 확인되지 않아 종료하지 않았습니다.")
    venv = _windows_path(str(project_root / ".venv" / "Scripts" / "python.exe"))
    matching_parents = [parent for parent in parents if isinstance(parent, dict) and parent.get("pid") == listener["parentPid"]]
    wrapper = None
    if len(matching_parents) > 1:
        raise ServerControlError("서버의 상위 프로세스가 명확하지 않아 종료하지 않았습니다.")
    if matching_parents:
        candidate = _identity(matching_parents[0])
        if _windows_path(candidate["executablePath"]) == venv and _application_command(candidate, project_root):
            if datetime.fromisoformat(candidate["creationTime"].replace("Z", "+00:00")) > datetime.fromisoformat(listener["creationTime"].replace("Z", "+00:00")):
                raise ServerControlError("상위 프로세스 번호가 재사용된 것으로 보여 종료하지 않았습니다.")
            wrapper = candidate
    if _windows_path(listener["executablePath"]) != venv and wrapper is None:
        raise ServerControlError("이 프로젝트의 Python 실행 환경이 아니므로 종료하지 않았습니다.")
    result = [{**listener, "role": "listener"}]
    if wrapper:
        result.append({**wrapper, "role": "wrapper"})
    return result


def _run(script: str, port: int, identities: list[dict[str, Any]] | None = None) -> str:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ServerControlError("서버 포트 번호가 올바르지 않습니다.")
    environment = os.environ.copy()
    environment["BRIEF_CONTROL_PORT"] = str(port)
    if identities is not None:
        environment["BRIEF_CONTROL_IDENTITIES"] = json.dumps(identities, ensure_ascii=False)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=environment, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ServerControlError("서버 프로세스를 확인하거나 종료하지 못했습니다. 실행 창의 상태를 확인해 주세요.") from error
    if result.returncode:
        # Do not repeat raw command lines, environment values, or arbitrary
        # PowerShell diagnostics in a user-facing error.
        raise ServerControlError("서버 프로세스 확인·종료가 거부됐거나 실행 상태가 바뀌었습니다. 다른 프로세스는 종료하지 않습니다.")
    return result.stdout


def inspect_server(project_root: Path, port: int = 5002) -> list[dict[str, Any]]:
    """Find a project-owned listener and (only if applicable) its venv wrapper."""
    try:
        payload = json.loads(_run(_INSPECT_SCRIPT, port))
    except (ValueError, TypeError) as error:
        raise ServerControlError("서버 프로세스 응답 형식을 확인하지 못했습니다.") from error
    if not isinstance(payload, dict):
        raise ServerControlError("서버 프로세스 응답 형식을 확인하지 못했습니다.")
    return _verify_snapshot(project_root, payload.get("listeners"), payload.get("parents"))


def stop_server(project_root: Path, identities: list[dict[str, Any]], port: int = 5002) -> None:
    """After caller authorization/state checks, stop these exact project IDs."""
    if not isinstance(identities, list) or not 1 <= len(identities) <= 2:
        raise ServerControlError("종료할 서버 프로세스를 확인하지 못했습니다.")
    listeners = [identity for identity in identities if isinstance(identity, dict) and identity.get("role") == "listener"]
    parents = [identity for identity in identities if isinstance(identity, dict) and identity.get("role") == "wrapper"]
    verified = _verify_snapshot(project_root, listeners, parents)
    if not verified or verified != identities:
        raise ServerControlError("서버 프로세스 정보가 변경돼 종료하지 않았습니다.")
    # A second read also protects the time spent at the launcher's confirmation
    # prompt. The stop script checks again in its own process before each stop.
    if inspect_server(project_root, port) != verified:
        raise ServerControlError("확인 중 서버가 변경돼 종료하지 않았습니다. 다시 실행해 주세요.")
    _run(_STOP_SCRIPT, port, verified)
