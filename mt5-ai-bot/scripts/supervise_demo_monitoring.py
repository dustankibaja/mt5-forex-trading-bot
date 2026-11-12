"""Windows user-session supervisor for the source-bound observer and read-only API."""
from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.monitoring.demo_account_snapshot import capture_demo_snapshot, invalidate_demo_snapshot
from src.monitoring.demo_controls import pause_demo
from src.monitoring.recovery import (
    BLOCKED, RETRY, Backoff, RecoveryBlocked, RecoveryUnavailable,
    read_binding, verify_session, windows_lock,
)
from src.monitoring.shadow_diagnostics import ProspectiveJournal
from src.monitoring.status_snapshot import public_snapshot, publish_status

LOG = logging.getLogger("demo_monitoring")


def _windows_job():
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION. The last supervisor handle closes
    # on process death, so its owned children cannot become orphan writers.
    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
            ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic), ("io", ctypes.c_ulonglong * 6),
            ("memory", ctypes.c_size_t * 4),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)
    return kernel, job


def read_existing_token(runtime):
    token_path = runtime / "read-token.dpapi"
    if not token_path.is_file():
        raise RecoveryBlocked("existing_pairing_token_required")
    command = (
        "$ErrorActionPreference='Stop'; "
        "$cipher=(Get-Content -LiteralPath $env:EMTIFIZE_DPAPI_FILE -Raw -Encoding UTF8).Trim(); "
        "$secure=ConvertTo-SecureString -String $cipher; "
        "$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); "
        "try {[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr))} "
        "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}"
    )
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "EMTIFIZE_DPAPI_FILE": str(token_path)}, capture_output=True,
        text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    token = result.stdout.strip()
    if result.returncode or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise RecoveryBlocked("existing_pairing_token_unavailable")
    return token


def check_legacy_observer():
    command = (
        "$ErrorActionPreference='Stop'; "
        """$p=Get-CimInstance Win32_Process -Filter "Name='python.exe'"; """
        "if($p | Where-Object {$_.CommandLine -like '*run_shadow_diagnostics.py*--watch*'}){exit 3}"
    )
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RecoveryBlocked("legacy_observer_present_or_inventory_failed")


def terminal_running(terminal):
    command = (
        "$ErrorActionPreference='Stop'; "
        "if(!(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
        "Where-Object {$_.ExecutablePath -eq $env:EMTIFIZE_TERMINAL_EXE})){exit 2}"
    )
    return subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "EMTIFIZE_TERMINAL_EXE": str(terminal)}, capture_output=True,
        timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode == 0


def api_health(port, token):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/v1/status", headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        if response.status != 200:
            return False
        status = json.loads(response.read(16_384))
        if status.get("trading_enabled") is not False or status.get("mode") == "live_configuration":
            raise RecoveryBlocked("unexpected_api_execution_state")
        return True
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def publish_offline(runtime):
    invalidate_demo_snapshot(runtime / "demo_account.json")
    publish_status(runtime / "engine_status.json", state="offline", dry_run=True, symbols=[])


def observer(runtime, terminal):
    import MetaTrader5 as mt5

    journal_path = runtime / "forward-observations.sqlite3"
    with windows_lock(journal_path.with_suffix(".lock")):
        binding = read_binding(journal_path)
        if not terminal_running(terminal):
            raise RecoveryUnavailable("terminal_process_unavailable")
        if not mt5.initialize(str(terminal), timeout=5000):
            raise RecoveryUnavailable("terminal_ipc_unavailable")
        try:
            expected = verify_session(mt5, binding, terminal)
            journal = ProspectiveJournal(journal_path, existing_only=True)
            journal.identity = expected
            while True:
                verify_session(mt5, binding, terminal)
                try:
                    journal.poll(mt5)
                except RuntimeError as exc:
                    verify_session(mt5, binding, terminal)
                    if "identity" in str(exc) or "session changed" in str(exc):
                        raise RecoveryBlocked("observer_identity_changed") from exc
                    raise RecoveryUnavailable("observer_poll_failed") from exc
                capture_demo_snapshot(mt5, runtime / "demo_account.json", expected_identity=expected)
                verify_session(mt5, binding, terminal)
                publish_status(runtime / "engine_status.json", state="paused", dry_run=True,
                               symbols=["EURUSD"], demo_guarded=True)
                time.sleep(15)
        finally:
            mt5.shutdown()
            publish_offline(runtime)


def supervise(runtime, terminal, port):
    from socket import socket

    with windows_lock(runtime / "demo-supervisor.lock"):
        stop_flag = runtime / "demo-supervisor.stop"
        if stop_flag.exists():
            raise RecoveryBlocked("operator_stop_present")
        read_binding(runtime / "forward-observations.sqlite3")
        check_legacy_observer()
        with socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RecoveryBlocked("status_port_already_in_use")
        token = read_existing_token(runtime)
        pause_demo(runtime / "remote_pause.flag")
        publish_offline(runtime)
        kernel, job = _windows_job()
        children = {}
        started = {}
        retry_at = {"observer": 0, "api": 0}
        budgets = {name: Backoff() for name in retry_at}
        logs = runtime / "logs"
        logs.mkdir(exist_ok=True)

        # Launch the verified base interpreter directly to avoid the Windows
        # venv launcher creating a second Python process. Use only its venv's
        # third-party packages. Absolute script paths select the checked code.
        base = Path(sys._base_executable).resolve(strict=True)
        packages = Path(sys.prefix) / "Lib" / "site-packages"
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("BOT_", "PYTHON"))}
        environment["PYTHONPATH"] = str(packages.resolve(strict=True))
        commands = {
            "observer": [str(Path(__file__).resolve()), "--runtime", str(runtime),
                         "--terminal", str(terminal), "--worker"],
            "api": [str(ROOT / "scripts/serve_status.py"), "--port", str(port),
                    "--status-path", str(runtime / "engine_status.json"),
                    "--demo-path", str(runtime / "demo_account.json"),
                    "--pause-path", str(runtime / "remote_pause.flag")],
        }

        def stop_child(name):
            child = children.pop(name, None)
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

        try:
            while not stop_flag.exists():
                now = time.monotonic()
                for name, command in commands.items():
                    child = children.get(name)
                    if child is None and now >= retry_at[name]:
                        # Never let the API bind an occupied port, even if a
                        # foreign process took it during recovery.
                        if name == "api":
                            with socket() as probe:
                                probe.settimeout(1)
                                if probe.connect_ex(("127.0.0.1", port)) == 0:
                                    raise RecoveryBlocked("status_port_already_in_use")
                        env = {**environment, "BOT_STATUS_READ_TOKEN": token} if name == "api" else environment
                        with (logs / f"supervised-{name}.log").open("ab") as output:
                            child = subprocess.Popen([str(base), "-B", "-s", "-u", *command],
                                                     cwd=runtime.parent, env=env, stdout=output,
                                                     stderr=subprocess.STDOUT,
                                                     creationflags=subprocess.CREATE_NO_WINDOW)
                        if not kernel.AssignProcessToJobObject(job, int(child._handle)):
                            error = ctypes.get_last_error()
                            child.terminate()
                            child.wait(timeout=5)
                            raise OSError(error, "Could not contain monitoring child")
                        children[name] = child
                        started[name] = now
                        LOG.info("started component=%s pid=%d", name, child.pid)
                        continue
                    if child is None:
                        continue
                    code = child.poll()
                    if name == "observer" and code == BLOCKED:
                        raise RecoveryBlocked("observer_safety_block_see_log")
                    age = now - started[name]
                    healthy = True
                    if code is None and age >= 40:
                        healthy = (api_health(port, token) if name == "api" else
                                   public_snapshot(runtime / "engine_status.json")["state"] == "paused")
                    if code is not None or not healthy:
                        LOG.warning("failure component=%s reason=%s", name,
                                    f"exit_{code}" if code is not None else "heartbeat")
                        stop_child(name)
                        if name == "observer":
                            publish_offline(runtime)
                        delay = budgets[name].delay()
                        retry_at[name] = now + delay
                        LOG.info("backoff component=%s seconds=%d", name, delay)
                    elif age >= 300:
                        budgets[name].failures = 0
                time.sleep(2)
        finally:
            kernel.CloseHandle(job)
            for child in children.values():
                child.wait(timeout=5)
            publish_offline(runtime)
            LOG.info("monitoring stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt" or not 1024 <= args.port <= 65535:
        parser.error("Windows and a valid loopback port are required")
    runtime = args.runtime.resolve(strict=True)
    terminal = args.terminal.resolve(strict=True)
    if runtime.name != "runtime" or terminal.name.lower() != "terminal64.exe":
        parser.error("Provide the existing deployment runtime and installed terminal64.exe")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.worker:
            observer(runtime, terminal)
        else:
            supervise(runtime, terminal, args.port)
    except (RecoveryBlocked, sqlite3.Error) as exc:
        LOG.error("blocked reason=%s", str(exc) if isinstance(exc, RecoveryBlocked) else "sqlite_failure")
        return BLOCKED
    except RecoveryUnavailable as exc:
        LOG.warning("temporarily unavailable reason=%s", exc)
        return RETRY
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
