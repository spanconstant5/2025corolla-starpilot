from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openpilot.common.params import Params
from openpilot.selfdrive.car.toyota_tss3_request_signer import (
  COROLLA_TSS3_MODEL,
  TSS3_SIGNER_STARTUP_BRIDGE_PARAM,
  TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH,
  TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH,
  request_signer_kit_compatibility,
)


DEFAULT_TOOL_PATH = Path("/data/tss3-oracle/tss3-request-signer")
DEFAULT_RUN_ROOT = Path("/data/tss3-oracle-runs")
CANCEL_FILENAME = "cancel-requested"
STATUS_SCHEMA = "tss3-request-signer-ui-status-v1"
INSTALL_SCHEMA = "tss3-request-signer-install-v1"
INSTALL_PASS_VERDICT = "request_signer_live_probe_pass"
OPENPILOT_SUMMARY_SCHEMA = "tss3-openpilot-bringup-summary-v2"
OPENPILOT_SUMMARY_FILENAME = "openpilot-bringup-summary.json"
STARTUP_BRIDGE_READY_TIMEOUT_S = 4.0

STAGE_LABELS = {
  "arming": "starting",
  "armed": "waiting for brake + POWER",
  "programming": "installing RAM signer",
  "waiting_ready": "waiting for READY / Park",
  "verifying": "checking peer health + signer",
  "finishing": "waiting for backend exit",
  "done": "complete",
  "error": "failed",
}


def stage_instruction(stage: str, *, signer_installed: bool = False) -> tuple[str, str]:
  """Return the operator action for the current phase, not stale startup text."""
  if stage == "arming":
    return "next step", "do not press POWER yet\nwait for the armed status"
  if stage == "armed":
    return "startup catcher armed", "press brake + POWER normally\nkeep the vehicle in Park"
  if stage in ("programming", "waiting_ready", "verifying", "finishing"):
    return "bringup in progress", "no action needed\nkeep the vehicle in Park"
  if stage == "done":
    return "bringup complete", "signer live; safety restored"
  if signer_installed:
    return "verification incomplete", "signer probe passed\ndo not drive; review saved result"
  return "bringup stopped", "do not drive\nreview the error and saved result"


def parse_status(line: str) -> dict[str, Any] | None:
  try:
    row = json.loads(line)
  except json.JSONDecodeError:
    return None
  if not isinstance(row, dict) or row.get("schema") != STATUS_SCHEMA:
    return None
  if not all(isinstance(row.get(key), str) for key in ("stage", "title", "detail")):
    return None
  if type(row.get("progress")) is not int or not 0 <= row["progress"] <= 100:
    return None
  if type(row.get("done")) is not bool or type(row.get("error")) is not bool:
    return None
  if row["done"] != (row["stage"] == "done") or row["error"] != (row["stage"] == "error"):
    return None
  return row


class SignerStatus:
  """Validate backend output. Completion requires both a done status and clean exit."""

  def __init__(self):
    self._status: dict[str, Any] | None = None
    self._last_output = ""

  def feed(self, line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
      return None
    status = parse_status(line)
    if status is None:
      self._last_output = line
      return None
    if self._status is not None and self._status["error"]:
      return None
    self._status = status
    return status

  def finish(self, returncode: int) -> dict[str, Any]:
    if self._status is not None and (self._status["error"] or (returncode == 0 and self._status["done"])):
      return self._status
    detail = f"Backend exited with status {returncode}." if returncode != 0 else "Backend exited without a completion status."
    if self._last_output:
      detail += f" Last output: {self._last_output}"
    return {
      "schema": STATUS_SCHEMA,
      "stage": "error",
      "title": "Request-signer bringup stopped",
      "detail": detail,
      "progress": 0,
      "done": False,
      "error": True,
    }


def request_cooperative_cancel(run_dir: Path) -> None:
  """Cancel only before the backend has crossed the EPS PROGRAMMING boundary."""
  try:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / CANCEL_FILENAME).write_text("cancel\n", encoding="utf-8")
  except OSError:
    # A late/running backend is safer than force-killing an EPS handoff.
    pass


def _load_json_object(path: Path) -> dict[str, Any] | None:
  try:
    value = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return None
  return value if isinstance(value, dict) else None


def signer_install_proven(run_dir: Path | None) -> bool:
  if run_dir is None:
    return False
  install = _load_json_object(run_dir / "request-signer-install.json")
  return bool(install is not None and
              install.get("schema") == INSTALL_SCHEMA and
              install.get("verdict") == INSTALL_PASS_VERDICT)


def classify_control_domain_state(control_state: dict[str, Any] | None) -> dict[str, str]:
  """Classify only fault evidence that the saved result actually establishes.

  Kai's current peer-health helper decodes a Camry 10-byte Brake 0x102F
  layout. This Corolla returned eight bytes on the bench. Treat an unsupported
  monitor as unknown instead of converting it into an observed vehicle fault.
  Affirmative Brake failure/communication bits still fail closed.
  """
  if control_state is None:
    return {"state": "inconclusive", "reason": "control_domain_state_missing"}

  fault_state = control_state.get("fault_state")
  brake = fault_state.get("brake") if isinstance(fault_state, dict) else None
  if not isinstance(brake, dict):
    return {"state": "inconclusive", "reason": "brake_fault_state_missing"}

  fail = brake.get("0x102D")
  if isinstance(fail, dict) and fail.get("available") is True:
    if fail.get("fail_status") is True or fail.get("fail_control") is True:
      return {"state": "fault", "reason": "brake_failure_bit_set"}

  comm = brake.get("0x102F")
  if isinstance(comm, dict) and comm.get("available") is True:
    if comm.get("eps_communication_open") is True:
      return {"state": "fault", "reason": "brake_eps_communication_open"}
    if isinstance(fail, dict) and fail.get("available") is True:
      return {"state": "healthy", "reason": "brake_peer_monitors_clear"}

  if isinstance(comm, dict):
    error = str(comm.get("error", "")).lower()
    if "unsupported/truncated data" in error:
      return {"state": "inconclusive", "reason": "brake_0x102f_layout_unsupported"}

  if control_state.get("peer_health_observed") is True:
    return {"state": "healthy", "reason": "backend_peer_health_pass"}
  return {"state": "inconclusive", "reason": "peer_monitor_unavailable"}


def _param_text(params: Params, key: str) -> str:
  value = params.get(key, encoding="utf-8")
  return value if isinstance(value, str) else ""


def _read_bridge_token(path: Path) -> str | None:
  try:
    token = path.read_text(encoding="utf-8").strip()
    return token or None
  except OSError:
    return None


def _cleanup_bridge_files(token: str) -> None:
  for path in (TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH, TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH):
    if _read_bridge_token(path) == token:
      path.unlink(missing_ok=True)


def _wait_for_startup_bridge(token: str, cancelled: threading.Event,
                             timeout: float = STARTUP_BRIDGE_READY_TIMEOUT_S) -> bool:
  deadline = time.monotonic() + timeout
  while not cancelled.is_set() and time.monotonic() < deadline:
    if _read_bridge_token(TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH) == token:
      return True
    time.sleep(0.02)
  return False


def _write_openpilot_summary(run_dir: Path | None, status: dict[str, Any], params: Params,
                             startup_bridge_requested: bool, startup_bridge_acknowledged: bool) -> None:
  if run_dir is None:
    return
  control_state = _load_json_object(run_dir / "control-domain-state.json")
  summary = {
    "schema": OPENPILOT_SUMMARY_SCHEMA,
    "openpilot": {
      "version": _param_text(params, "Version"),
      "git_commit": _param_text(params, "GitCommit"),
      "git_branch": _param_text(params, "GitBranch"),
      "git_remote": _param_text(params, "GitRemote"),
      "dirty": bool(_param_text(params, "GitDiff")),
    },
    "startup_bridge": {
      "supported": True,
      "requested": startup_bridge_requested,
      "acknowledged": startup_bridge_acknowledged,
    },
    "signer_installed": signer_install_proven(run_dir),
    "vehicle_health": classify_control_domain_state(control_state),
    "ui_status": status,
  }
  try:
    run_dir.mkdir(parents=True, exist_ok=True)
    destination = run_dir / OPENPILOT_SUMMARY_FILENAME
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
  except OSError:
    # The original backend artifacts remain authoritative if storage changes
    # underneath the UI process while it is finalizing.
    pass


def preserve_install_result(run_dir: Path | None, status: dict[str, Any]) -> dict[str, Any]:
  """Do not collapse a proven install into an ambiguous backend failure."""
  if run_dir is None or not status.get("error"):
    return status

  install = _load_json_object(run_dir / "request-signer-install.json")
  if install is None or install.get("schema") != INSTALL_SCHEMA or install.get("verdict") != INSTALL_PASS_VERDICT:
    return status

  control_state = _load_json_object(run_dir / "control-domain-state.json")
  health = classify_control_domain_state(control_state)
  if health["state"] == "fault":
    detail = "The RAM signer live probe passed, but a Brake/EPS peer-health fault was observed. " + \
             "Keep the vehicle parked and review the saved result."
  elif health["reason"] == "brake_0x102f_layout_unsupported":
    detail = "The RAM signer live probe passed and Brake failure bits were clear. This Corolla's 8-byte " + \
             "Brake 0x102F layout is not decoded by the Camry-oriented verifier, so vehicle health remains " + \
             "inconclusive. Keep the vehicle parked and review the saved result."
  else:
    detail = "The RAM signer live probe passed, but final vehicle-health verification was inconclusive. " + \
             "Keep the vehicle parked and review the saved result."

  return {
    **status,
    "title": "RAM signer installed; verification incomplete",
    "detail": detail,
    "progress": max(80, int(status.get("progress", 0))),
    "signer_installed": True,
    "vehicle_health": health["state"],
    "vehicle_health_reason": health["reason"],
  }


class Tss3SignerRunner:
  """Own one guided OFF-to-READY request-signer bringup process."""

  def __init__(self, tool_path: Path = DEFAULT_TOOL_PATH, run_root: Path = DEFAULT_RUN_ROOT, *, start: bool = True,
               params: Params | None = None):
    self._tool_path = tool_path
    self._run_root = run_root
    self._params = params if params is not None else Params()
    self._lock = threading.Lock()
    self._status: dict[str, Any] = {
      "stage": "arming",
      "title": "Arming Corolla RAM signer",
      "detail": "Preparing the EPS startup catcher. Do not press POWER yet.",
      "progress": 0,
      "done": False,
      "error": False,
    }
    self._proc: subprocess.Popen[str] | None = None
    self._run_dir: Path | None = None
    self._startup_bridge_requested = False
    self._startup_bridge_acknowledged = False
    self._launch_pending = False
    self._cancelled = threading.Event()
    if start:
      self.start()

  @property
  def run_dir(self) -> Path | None:
    return self._run_dir

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return dict(self._status)

  def _set_status(self, status: dict[str, Any]) -> None:
    with self._lock:
      self._status = dict(status)

  def start(self) -> None:
    if self._proc is not None or self._run_dir is not None or self._launch_pending:
      raise RuntimeError("TSS3 signer runner already started")

    check = request_signer_kit_compatibility(self._tool_path)
    if not check.compatible:
      self._set_status({
        "stage": "error",
        "title": "Corolla signer kit invalid",
        "detail": check.detail,
        "progress": 0,
        "done": False,
        "error": True,
      })
      return

    token = f"{os.getpid()}-{time.monotonic_ns()}"
    try:
      TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH.unlink(missing_ok=True)
      temporary = TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH.with_name(
        f".{TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH.name}.{os.getpid()}",
      )
      temporary.write_text(token + "\n", encoding="utf-8")
      os.replace(temporary, TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH)
      self._params.put_bool(TSS3_SIGNER_STARTUP_BRIDGE_PARAM, True)
    except Exception as exc:
      _cleanup_bridge_files(token)
      try:
        self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
      except Exception:
        pass
      self._set_status({
        "stage": "error",
        "title": "Could not prepare Corolla signer handoff",
        "detail": f"{type(exc).__name__}: {exc}",
        "progress": 0,
        "done": False,
        "error": True,
      })
      return

    self._startup_bridge_requested = True
    self._launch_pending = True
    threading.Thread(
      target=self._launch_after_bridge_ready,
      args=(token,),
      name="tss3_signer_bridge",
      daemon=True,
    ).start()

  def _launch_after_bridge_ready(self, token: str) -> None:
    if not _wait_for_startup_bridge(token, self._cancelled):
      self._launch_pending = False
      self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
      _cleanup_bridge_files(token)
      if not self._cancelled.is_set():
        self._set_status({
          "stage": "error",
          "title": "Corolla signer handoff did not become ready",
          "detail": "The lightweight card socket bridge did not acknowledge startup. The installer was not launched.",
          "progress": 0,
          "done": False,
          "error": True,
        })
      return

    _cleanup_bridge_files(token)
    self._startup_bridge_acknowledged = True
    self._launch_pending = False
    if self._cancelled.is_set():
      self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
      return

    stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    self._run_dir = self._run_root / f"ui-bringup-{stamp}-{os.getpid()}-{time.monotonic_ns()}"
    cmd = [str(self._tool_path), "ui-bringup", str(self._run_dir)]
    try:
      self._proc = subprocess.Popen(
        cmd,
        cwd=str(self._tool_path.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
      )
    except OSError as exc:
      self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
      self._set_status({
        "stage": "error",
        "title": "Could not arm Corolla RAM signer",
        "detail": f"{type(exc).__name__}: {exc}",
        "progress": 0,
        "done": False,
        "error": True,
      })
      return

    threading.Thread(target=self._reader, name="tss3_signer_ui", daemon=True).start()

  def request_cancel(self) -> None:
    self._cancelled.set()
    if self._launch_pending:
      self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
    status = self.snapshot()
    proc = self._proc
    if proc is not None and proc.poll() is None and not status.get("done") and not status.get("error") and self._run_dir is not None:
      request_cooperative_cancel(self._run_dir)

  def _reader(self) -> None:
    assert self._proc is not None and self._proc.stdout is not None
    report = SignerStatus()
    for raw in self._proc.stdout:
      status = report.feed(raw)
      if status is None:
        continue
      if status["done"]:
        self._set_status({
          **status,
          "stage": "finishing",
          "title": "Finalizing Corolla RAM signer",
          "detail": "Waiting for Panda ownership and normal safety mode to be restored.",
          "done": False,
        })
      else:
        self._set_status(status)

    status = preserve_install_result(self._run_dir, report.finish(self._proc.wait()))
    _write_openpilot_summary(
      self._run_dir, status, self._params, self._startup_bridge_requested, self._startup_bridge_acknowledged,
    )
    if signer_install_proven(self._run_dir):
      # The exact EPS live probe is stronger identity evidence than the
      # overlapping TSS3 vehicle census. Store the validated model so a later
      # ambiguous FPv1 run can recover it only when the live census also fits.
      self._params.put("CarMake", "Toyota")
      self._params.put("CarModel", COROLLA_TSS3_MODEL)
    else:
      self._params.remove(TSS3_SIGNER_STARTUP_BRIDGE_PARAM)
    self._set_status(status)
