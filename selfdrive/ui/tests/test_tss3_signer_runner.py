import io
import json
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.car.toyota_tss3_request_signer import SignerKitCheck
from openpilot.selfdrive.ui import tss3_signer_runner as runner


def status_row(**overrides):
  return {
    "schema": runner.STATUS_SCHEMA,
    "stage": "done",
    "title": "Bringup complete",
    "detail": "All checks passed.",
    "progress": 100,
    "done": True,
    "error": False,
    **overrides,
  }


def test_completion_requires_done_status_and_clean_exit():
  for returncode in (0, 2):
    report = runner.SignerStatus()
    report.feed(json.dumps(status_row(stage="verifying", done=False, progress=70)))
    report.feed(json.dumps(status_row()))
    result = report.finish(returncode)
    assert result["done"] is (returncode == 0)
    assert result["error"] is (returncode != 0)


def test_malformed_status_cannot_report_success():
  report = runner.SignerStatus()
  assert report.feed(json.dumps(status_row(progress=True))) is None
  result = report.finish(0)
  assert result["error"] is True
  assert result["done"] is False


def test_done_is_not_published_before_backend_exit():
  signer_runner = runner.Tss3SignerRunner(start=False)

  def wait_for_exit():
    status = signer_runner.snapshot()
    assert status["stage"] == "finishing"
    assert status["done"] is False
    return 0

  signer_runner._proc = SimpleNamespace(stdout=io.StringIO(json.dumps(status_row()) + "\n"), wait=wait_for_exit)
  signer_runner._reader()
  assert signer_runner.snapshot()["done"] is True


def test_cancel_is_cooperative_marker(tmp_path: Path):
  run_dir = tmp_path / "run"
  runner.request_cooperative_cancel(run_dir)
  assert (run_dir / runner.CANCEL_FILENAME).read_text(encoding="utf-8") == "cancel\n"


def test_proven_install_is_preserved_when_peer_verification_fails(tmp_path: Path):
  (tmp_path / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": runner.INSTALL_PASS_VERDICT,
  }), encoding="utf-8")
  (tmp_path / "control-domain-state.json").write_text(json.dumps({
    "peer_health_observed": False,
    "verdict": "control_domain_fault_observed",
  }), encoding="utf-8")
  failure = status_row(
    stage="error", title="UI bringup error", detail="peer fault state unhealthy",
    progress=70, done=False, error=True,
  )

  result = runner.preserve_install_result(tmp_path, failure)
  assert result["error"] is True
  assert result["done"] is False
  assert result["signer_installed"] is True
  assert result["progress"] == 80
  assert result["title"] == "RAM signer installed; verification incomplete"


def test_failed_or_missing_install_is_not_reclassified(tmp_path: Path):
  failure = status_row(stage="error", done=False, error=True)
  assert runner.preserve_install_result(tmp_path, failure) == failure

  (tmp_path / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": "request_signer_live_probe_failed",
  }), encoding="utf-8")
  assert runner.preserve_install_result(tmp_path, failure) == failure


def test_runner_invokes_guided_ui_bringup(tmp_path: Path, monkeypatch):
  commands = []

  class FakeProcess:
    stdout = io.StringIO()

    @staticmethod
    def poll():
      return None

    @staticmethod
    def wait():
      return 0

  class FakeThread:
    def __init__(self, *args, **kwargs):
      pass

    def start(self):
      pass

  def fake_popen(command, **kwargs):
    commands.append((command, kwargs))
    return FakeProcess()

  monkeypatch.setattr(runner, "request_signer_kit_compatibility", lambda _path: SignerKitCheck(True, "verified"))
  monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(runner.threading, "Thread", FakeThread)

  tool = tmp_path / "tss3-request-signer"
  signer_runner = runner.Tss3SignerRunner(tool, tmp_path / "runs")
  assert commands[0][0][0:2] == [str(tool), "ui-bringup"]
  assert signer_runner.run_dir is not None
  assert commands[0][0][2] == str(signer_runner.run_dir)
