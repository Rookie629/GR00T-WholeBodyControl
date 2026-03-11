from __future__ import annotations

from pathlib import Path
import subprocess
import threading
from typing import Callable


class ManagedProcess:
    def __init__(
        self,
        name: str,
        *,
        on_output: Callable[[str, str], None],
        on_state_change: Callable[[str, str], None],
    ):
        self.name = name
        self._on_output = on_output
        self._on_state_change = on_state_change
        self.process: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []

    def start(self, program: str, arguments: list[str], cwd: str | Path | None = None) -> None:
        if self.is_running():
            return
        self.process = subprocess.Popen(
            [program, *arguments],
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._on_state_change(self.name, "running")
        self._threads = [
            threading.Thread(target=self._pump_stream, args=(self.process.stdout,), daemon=True),
            threading.Thread(target=self._pump_stream, args=(self.process.stderr,), daemon=True),
            threading.Thread(target=self._wait_for_exit, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        if not self.is_running():
            return
        assert self.process is not None
        self.process.terminate()
        try:
            self.process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1.0)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_detached(self, program: str, arguments: list[str], cwd: str | Path | None = None) -> None:
        subprocess.Popen(
            [program, *arguments],
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _pump_stream(self, stream) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            payload = line.rstrip()
            if payload:
                self._on_output(self.name, payload)
        stream.close()

    def _wait_for_exit(self) -> None:
        if self.process is None:
            return
        exit_code = self.process.wait()
        status = "finished" if exit_code == 0 else "crashed"
        self._on_state_change(self.name, f"{status} ({exit_code})")
