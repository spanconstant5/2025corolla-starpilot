from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path


DIRECT_PANDA_LEASE_PATH = Path("/tmp/openpilot-pandad-direct-lease")
DIRECT_PANDA_LEASE_READY_PATH = Path("/tmp/openpilot-pandad-direct-ready")


class DirectPandaLease:
  """Token-validated handoff between pandad and a short-lived direct-Panda tool."""

  def __init__(self, lease_path: Path = DIRECT_PANDA_LEASE_PATH,
               ready_path: Path = DIRECT_PANDA_LEASE_READY_PATH) -> None:
    self.lease_path = lease_path
    self.ready_path = ready_path
    self.requested = False

  def _clear_ready(self, lease: str | None = None) -> None:
    try:
      if lease is None or self.ready_path.read_text(encoding="utf-8").strip() == lease:
        self.ready_path.unlink(missing_ok=True)
    except FileNotFoundError:
      pass

  def active(self) -> str | None:
    try:
      lease = self.lease_path.read_text(encoding="utf-8").strip()
      pid_text, token = lease.split(" ", 1)
      if not pid_text.isdecimal() or int(pid_text) <= 0 or not token:
        raise ValueError("invalid direct-Panda lease")
      os.kill(int(pid_text), 0)
      return lease
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
      self.lease_path.unlink(missing_ok=True)
      self._clear_ready()
      return None

  def request(self) -> str | None:
    lease = self.active()
    self.requested = lease is not None
    return lease

  def _publish_ready(self, lease: str) -> None:
    tmp = self.ready_path.with_name(f".{self.ready_path.name}.{os.getpid()}")
    tmp.write_text(lease + "\n", encoding="utf-8")
    os.replace(tmp, self.ready_path)

  def hold(self, should_stop: Callable[[], bool]) -> bool:
    lease = self.active()
    self.requested = False
    if lease is None:
      return False

    self._publish_ready(lease)
    try:
      while not should_stop() and self.active() == lease:
        time.sleep(0.05)
    finally:
      self._clear_ready(lease)
    return True


class DirectPandaLeaseRunner:
  """Runs native pandad while retaining the managed Python supervisor."""

  def __init__(self, lease: DirectPandaLease | None = None,
               popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
    self.lease = lease or DirectPandaLease()
    self._popen = popen
    self._process: subprocess.Popen | None = None
    self._stop = False

  def _interrupt_child(self) -> None:
    if self._process is not None and self._process.poll() is None:
      self._process.send_signal(signal.SIGINT)

  def shutdown(self) -> None:
    self._stop = True
    self._interrupt_child()

  def request_lease(self) -> str | None:
    lease = self.lease.request()
    if lease is not None:
      self._interrupt_child()
    return lease

  def run(self, command: Sequence[str], cwd: str) -> None:
    """Return only for shutdown or an unrequested native-child exit."""
    while not self._stop:
      active_lease = self.lease.active()
      if self.lease.requested or active_lease is not None:
        self.lease.hold(lambda: self._stop)
        continue

      self._process = self._popen(command, cwd=cwd)
      self._process.wait()
      self._process = None
      if self._stop:
        return

      active_lease = self.lease.active()
      if self.lease.requested or active_lease is not None:
        self.lease.hold(lambda: self._stop)
        continue

      # Preserve the existing recovery behavior for an unrequested pandad exit.
      return
