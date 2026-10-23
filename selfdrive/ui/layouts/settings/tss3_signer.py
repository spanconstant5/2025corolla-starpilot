from __future__ import annotations

import threading

from openpilot.selfdrive.car.toyota_tss3_request_signer import request_signer_kit_compatibility
from openpilot.selfdrive.ui.tss3_signer_runner import STAGE_LABELS, Tss3SignerRunner
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog


_state_lock = threading.Lock()
_state = "ARM"


def signer_install_status() -> str:
  with _state_lock:
    return _state


def _set_state(state: str) -> None:
  global _state
  with _state_lock:
    _state = state


class CorollaSignerBringupDialog(ConfirmDialog):
  def __init__(self):
    super().__init__(
      tr("Preparing the Corolla RAM signer startup catcher. Do not press POWER yet."),
      tr("CLOSE"),
      cancel_text="",
    )
    self._confirm_button.set_enabled(False)
    self._runner = Tss3SignerRunner()
    self._terminal_rendered = False
    _set_state("ARMING")

  def hide_event(self):
    self._runner.request_cancel()
    super().hide_event()

  def _update_state(self):
    status = self._runner.snapshot()
    stage = status["stage"]
    progress = status["progress"]
    run_dir = self._runner.run_dir
    saved = f"\n\nResults: {run_dir}" if run_dir is not None else ""
    self.set_text(
      f"{status['title']}\n\n{status['detail']}\n\n{progress}% — {STAGE_LABELS.get(stage, stage)}{saved}"
    )
    if status["done"] or status["error"]:
      if not self._terminal_rendered:
        _set_state("ARM" if status["done"] else "RETRY")
        self._confirm_button.set_enabled(True)
        self._terminal_rendered = True
    else:
      _set_state(stage.upper())


# Compatibility alias retained for existing imports.
CorollaSignerInstallDialog = CorollaSignerBringupDialog


def request_corolla_signer_install() -> None:
  check = request_signer_kit_compatibility()
  if not check.compatible:
    _set_state("KIT ERROR")
    gui_app.push_widget(alert_dialog(check.detail))
    return

  def on_confirm(result: DialogResult) -> None:
    if result == DialogResult.CONFIRM:
      gui_app.push_widget(CorollaSignerBringupDialog())

  content = tr("Arm the verified Corolla signer while the vehicle is fully OFF/not READY and in Park.\n\n")
  content += tr("After the page says it is armed, press the brake and POWER normally. Keep the vehicle in Park until verification passes. ")
  content += tr("This writes only volatile EPS RAM; a full EPS power loss removes the signer.")
  gui_app.push_widget(ConfirmDialog(content, tr("ARM"), callback=on_confirm))
