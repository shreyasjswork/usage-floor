"""Operating-system helpers: process checks, a windowless background launch and sign-in autostart."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | CREATE_NO_WINDOW
SHORTCUT_NAME = "Usage Floor supervisor.lnk"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes  # noqa: PLC0415 -- Windows only

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(pid: int) -> None:
    if WINDOWS:
        import ctypes  # noqa: PLC0415 -- Windows only

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)


def background_python() -> str:
    """`pythonw.exe` next to the running interpreter on Windows, so no console window opens."""
    if WINDOWS:
        windowless = Path(sys.executable).with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return sys.executable


def spawn_supervisor() -> None:
    command = [background_python(), "-m", "usage_floor", "run"]
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                     "close_fds": True}
    if WINDOWS:
        options["creationflags"] = DETACHED
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)  # noqa: S603 -- our own interpreter and module


def startup_shortcut() -> Path | None:
    if not WINDOWS:
        return None
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup / SHORTCUT_NAME


def autostart_enabled() -> bool:
    shortcut = startup_shortcut()
    return bool(shortcut and shortcut.exists())


def set_autostart(enabled: bool) -> str:
    shortcut = startup_shortcut()
    if shortcut is None:
        return "Start at sign-in is only automated on Windows. Add `python -m usage_floor run` to your session startup."
    if not enabled:
        with contextlib.suppress(OSError):
            shortcut.unlink()
        return "The supervisor will not start at sign-in."
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:UF_LNK);"
        "$s.TargetPath=$env:UF_TARGET;$s.Arguments='-m usage_floor run';"
        "$s.WorkingDirectory=$env:UF_DIR;$s.WindowStyle=7;$s.Save()"
    )
    env = {**os.environ, "UF_LNK": str(shortcut), "UF_TARGET": background_python(), "UF_DIR": str(Path.home())}
    system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    subprocess.run(  # noqa: S603 -- fixed system executable, script passes values through the environment
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        env=env, check=True, capture_output=True, creationflags=0x08000000,
    )
    return "The supervisor will start at sign-in."
