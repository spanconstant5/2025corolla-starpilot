from __future__ import annotations

import threading

from openpilot.selfdrive.car.toyota_tss3_request_signer import (
  SignerInstallResult,
  request_signer_kit_compatibility,
  run_request_signer_install,
)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog


_state_lock = threading.Lock()
_state = "INSTALL"


def signer_install_status() -> str:
  with _state_lock:
    return _state


def _set_state(state: str) -> None:
  global _state
  with _state_lock:
    _state = state


class CorollaSignerInstallDialog(ConfirmDialog):
  def __init__(self):
    super().__init__(
      tr("Installing the volatile Corolla RAM signer. Keep the vehicle in Park and do not power it off."),
      tr("CLOSE"),
      cancel_text="",
    )
    self._confirm_button.set_enabled(False)
    self._result_lock = threading.Lock()
    self._result: SignerInstallResult | None = None
    self._rendered_result = False
    _set_state("INSTALLING")
    threading.Thread(target=self._worker, name="corolla-ram-signer", daemon=True).start()

  def _worker(self) -> None:
    try:
      result = run_request_signer_install()
    except Exception as exc:
      result = SignerInstallResult(
        False,
        "RAM signer installer stopped unexpectedly",
        f"{type(exc).__name__}: {exc}. Do not drive; Panda safety may require an openpilot reboot.",
      )
    with self._result_lock:
      self._result = result
    _set_state("INSTALL" if result.passed else "RETRY")

  def _update_state(self):
    with self._result_lock:
      result = self._result
    if result is None or self._rendered_result:
      return

    self._rendered_result = True
    saved = f"\n\nResult: {result.output_path}" if result.output_path is not None else ""
    self.set_text(f"{result.title}\n\n{result.detail}{saved}")
    self._confirm_button.set_enabled(True)


def request_corolla_signer_install() -> None:
  check = request_signer_kit_compatibility()
  if not check.compatible:
    _set_state("KIT ERROR")
    gui_app.push_widget(alert_dialog(check.detail))
    return

  def on_confirm(result: DialogResult) -> None:
    if result == DialogResult.CONFIRM:
      gui_app.push_widget(CorollaSignerInstallDialog())

  content = tr("Install the verified Corolla signer into volatile EPS RAM?\n\n")
  content += tr("Vehicle must be ON, in Park, with wheels straight. Do not drive or power off during the install. ")
  content += tr("This does not flash persistent EPS firmware. The signer must be installed again after the EPS loses power.")
  gui_app.push_widget(ConfirmDialog(content, tr("INSTALL"), callback=on_confirm))
