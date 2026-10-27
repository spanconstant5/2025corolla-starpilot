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


class MemoryParams:
  def __init__(self):
    self.values = {}

  def put(self, key, value):
    self.values[key] = value

  def put_bool(self, key, value):
    self.values[key] = bool(value)

  def remove(self, key):
    self.values.pop(key, None)


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


def test_stage_instruction_does_not_keep_showing_wait_for_armed():
  assert "wait for the armed" in runner.stage_instruction("arming")[1]
  assert "press brake + POWER" in runner.stage_instruction("armed")[1]
  assert "wait for the armed" not in runner.stage_instruction("verifying")[1]
  assert runner.stage_instruction("verifying")[0] == "bringup in progress"
  assert "signer probe passed" in runner.stage_instruction("error", signer_installed=True)[1]


def test_done_is_not_published_before_backend_exit():
  signer_runner = runner.Tss3SignerRunner(start=False, params=MemoryParams())

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


def test_corolla_short_102f_is_inconclusive_not_a_fault(tmp_path: Path):
  control_state = {
    "peer_health_observed": False,
    "fault_state": {
      "brake": {
        "0x102D": {
          "available": True,
          "fail_control": False,
          "fail_status": False,
          "raw": "30107f00ff007d00ef24c00010106040",
        },
        "0x102F": {
          "available": False,
          "error": "RecoveryError: Brake DID 0x102F has unsupported/truncated data: 0700000000000000",
        },
      },
    },
  }
  assert runner.classify_control_domain_state(control_state) == {
    "state": "inconclusive",
    "reason": "brake_0x102f_layout_unsupported",
  }

  (tmp_path / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": runner.INSTALL_PASS_VERDICT,
  }), encoding="utf-8")
  (tmp_path / "control-domain-state.json").write_text(json.dumps(control_state), encoding="utf-8")
  result = runner.preserve_install_result(tmp_path, status_row(stage="error", done=False, error=True))
  assert result["vehicle_health"] == "inconclusive"
  assert result["vehicle_health_reason"] == "brake_0x102f_layout_unsupported"
  assert "not decoded by the Camry-oriented verifier" in result["detail"]


def test_affirmative_brake_fault_is_not_reclassified_as_inconclusive():
  control_state = {
    "peer_health_observed": False,
    "fault_state": {
      "brake": {
        "0x102D": {"available": True, "fail_control": True, "fail_status": False},
        "0x102F": {"available": False, "error": "unsupported/truncated data"},
      },
    },
  }
  assert runner.classify_control_domain_state(control_state) == {
    "state": "fault",
    "reason": "brake_failure_bit_set",
  }


def test_reader_writes_persistent_openpilot_summary(tmp_path: Path):
  run_dir = tmp_path / "run"
  run_dir.mkdir()
  (run_dir / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": runner.INSTALL_PASS_VERDICT,
  }), encoding="utf-8")

  signer_runner = runner.Tss3SignerRunner(start=False, params=MemoryParams())
  signer_runner._run_dir = run_dir
  signer_runner._proc = SimpleNamespace(stdout=io.StringIO(json.dumps(status_row()) + "\n"), wait=lambda: 0)
  signer_runner._reader()

  summary = json.loads((run_dir / runner.OPENPILOT_SUMMARY_FILENAME).read_text(encoding="utf-8"))
  assert summary["schema"] == runner.OPENPILOT_SUMMARY_SCHEMA
  assert summary["signer_installed"] is True
  assert summary["vehicle_health"]["state"] == "inconclusive"
  assert summary["ui_status"]["done"] is True


def test_proven_signer_probe_persists_corolla_identity(tmp_path: Path):
  run_dir = tmp_path / "run"
  run_dir.mkdir()
  (run_dir / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": runner.INSTALL_PASS_VERDICT,
  }), encoding="utf-8")
  params = MemoryParams()
  params.put_bool(runner.TSS3_SIGNER_STARTUP_BRIDGE_PARAM, True)
  signer_runner = runner.Tss3SignerRunner(start=False, params=params)
  signer_runner._run_dir = run_dir
  signer_runner._proc = SimpleNamespace(stdout=io.StringIO(json.dumps(status_row()) + "\n"), wait=lambda: 0)

  signer_runner._reader()

  assert params.values["CarMake"] == "Toyota"
  assert params.values["CarModel"] == runner.COROLLA_TSS3_MODEL
  assert params.values[runner.TSS3_SIGNER_STARTUP_BRIDGE_PARAM] is True


def test_failed_signer_probe_does_not_persist_corolla_identity(tmp_path: Path):
  (tmp_path / "request-signer-install.json").write_text(json.dumps({
    "schema": runner.INSTALL_SCHEMA,
    "verdict": "request_signer_live_probe_failed",
  }), encoding="utf-8")
  params = MemoryParams()
  params.put_bool(runner.TSS3_SIGNER_STARTUP_BRIDGE_PARAM, True)
  signer_runner = runner.Tss3SignerRunner(start=False, params=params)
  signer_runner._run_dir = tmp_path
  signer_runner._proc = SimpleNamespace(
    stdout=io.StringIO(json.dumps(status_row(stage="error", done=False, error=True)) + "\n"),
    wait=lambda: 1,
  )

  signer_runner._reader()

  assert params.values == {}


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
  params = MemoryParams()
  signer_runner = runner.Tss3SignerRunner(tool, tmp_path / "runs", params=params)
  assert commands[0][0][0:2] == [str(tool), "ui-bringup"]
  assert signer_runner.run_dir is not None
  assert commands[0][0][2] == str(signer_runner.run_dir)
  assert params.values[runner.TSS3_SIGNER_STARTUP_BRIDGE_PARAM] is True


def test_runner_releases_startup_bridge_when_tool_cannot_launch(tmp_path: Path, monkeypatch):
  def fail_popen(*_args, **_kwargs):
    raise OSError("missing")

  monkeypatch.setattr(runner, "request_signer_kit_compatibility", lambda _path: SignerKitCheck(True, "verified"))
  monkeypatch.setattr(runner.subprocess, "Popen", fail_popen)

  params = MemoryParams()
  signer_runner = runner.Tss3SignerRunner(tmp_path / "tss3-request-signer", tmp_path / "runs", params=params)

  assert runner.TSS3_SIGNER_STARTUP_BRIDGE_PARAM not in params.values
  assert signer_runner.snapshot()["error"] is True
