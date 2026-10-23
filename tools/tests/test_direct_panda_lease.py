from __future__ import annotations

import importlib.util
import os
import signal
import sys
import threading
import time
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "selfdrive" / "pandad" / "direct_panda_lease.py"
SPEC = importlib.util.spec_from_file_location("direct_panda_lease_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
direct_panda_lease = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = direct_panda_lease
SPEC.loader.exec_module(direct_panda_lease)
DirectPandaLease = direct_panda_lease.DirectPandaLease
DirectPandaLeaseRunner = direct_panda_lease.DirectPandaLeaseRunner


def _live_lease() -> str:
  return f"{os.getpid()} direct-panda-lease-test"


def test_invalid_lease_fails_closed_and_cleans_stale_ready(tmp_path: Path):
  lease_path = tmp_path / "lease"
  ready_path = tmp_path / "ready"
  lease_path.write_text("not-a-valid-lease\n", encoding="utf-8")
  ready_path.write_text("stale\n", encoding="utf-8")

  lease = DirectPandaLease(lease_path, ready_path)
  assert lease.active() is None
  assert not lease_path.exists()
  assert not ready_path.exists()

  lease_path.write_text("0 process-group-is-not-a-requester\n", encoding="utf-8")
  assert lease.active() is None
  assert not lease_path.exists()


def test_lease_acknowledges_only_while_requester_is_live(tmp_path: Path):
  lease_path = tmp_path / "lease"
  ready_path = tmp_path / "ready"
  token = _live_lease()
  lease_path.write_text(token + "\n", encoding="utf-8")
  lease = DirectPandaLease(lease_path, ready_path)

  observed = []

  def release_when_ready():
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
      if ready_path.exists():
        observed.append(ready_path.read_text(encoding="utf-8").strip())
        lease_path.unlink()
        return
      time.sleep(0.005)

  releaser = threading.Thread(target=release_when_ready)
  releaser.start()
  assert lease.hold(lambda: False)
  releaser.join(timeout=2.0)

  assert observed == [token]
  assert not ready_path.exists()


def test_runner_releases_only_native_child_and_restarts_without_recovery(tmp_path: Path):
  lease_path = tmp_path / "lease"
  ready_path = tmp_path / "ready"
  lease = DirectPandaLease(lease_path, ready_path)
  launches = []
  ready_observed = []
  runner = None

  class FakeProcess:
    def __init__(self, index: int):
      self.index = index
      self.signals = []
      self.exited = False

    def poll(self):
      return 0 if self.exited else None

    def send_signal(self, sig):
      self.signals.append(sig)
      self.exited = True

    def wait(self):
      if self.index == 0:
        token = _live_lease()
        lease_path.write_text(token + "\n", encoding="utf-8")

        def release_when_ready():
          deadline = time.monotonic() + 2.0
          while time.monotonic() < deadline:
            if ready_path.exists():
              ready_observed.append(ready_path.read_text(encoding="utf-8").strip())
              break
            time.sleep(0.005)
          lease_path.unlink(missing_ok=True)

        threading.Thread(target=release_when_ready, daemon=True).start()
        assert runner is not None
        assert runner.request_lease() == token
        self.exited = True
        return 0

      assert runner is not None
      runner.shutdown()
      self.exited = True
      return 0

  def fake_popen(*_args, **_kwargs):
    process = FakeProcess(len(launches))
    launches.append(process)
    return process

  runner = DirectPandaLeaseRunner(lease, popen=fake_popen)
  runner.run(["./pandad"], "/tmp")

  assert len(launches) == 2
  assert signal.SIGINT in launches[0].signals
  assert ready_observed == [_live_lease()]
  assert not ready_path.exists()


def test_runner_preserves_recovery_path_for_unrequested_exit(tmp_path: Path):
  launches = []

  class FakeProcess:
    def poll(self):
      return 1

    def wait(self):
      return 1

  def fake_popen(*_args, **_kwargs):
    process = FakeProcess()
    launches.append(process)
    return process

  runner = DirectPandaLeaseRunner(
    DirectPandaLease(tmp_path / "lease", tmp_path / "ready"),
    popen=fake_popen,
  )
  runner.run(["./pandad"], "/tmp")
  assert len(launches) == 1
