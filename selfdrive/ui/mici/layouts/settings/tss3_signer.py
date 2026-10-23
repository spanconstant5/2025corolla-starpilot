from __future__ import annotations

import threading

from cereal import car
from openpilot.selfdrive.car.toyota_tss3_request_signer import (
  SignerInstallResult,
  request_signer_kit_compatibility,
  run_request_signer_install,
)
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


COROLLA_TSS3_MODEL = "TOYOTA_COROLLA_TSS3"
_state_lock = threading.Lock()
_install_active = False


def corolla_tss3_selected() -> bool:
  return ui_state.params.get("CarModel", encoding="utf-8") == COROLLA_TSS3_MODEL


def signer_install_active() -> bool:
  with _state_lock:
    return _install_active


def _set_install_active(active: bool) -> None:
  global _install_active
  with _state_lock:
    _install_active = active


def can_install_corolla_signer() -> bool:
  if not corolla_tss3_selected() or signer_install_active() or ui_state.engaged or not ui_state.started:
    return False
  try:
    CS = ui_state.sm["carState"]
    return bool(CS.standstill) and CS.gearShifter == car.CarState.GearShifter.park
  except Exception:
    return False


class CorollaSignerInstallPage(NavScroller):
  """Comma 4 progress page that cannot be dismissed while the installer is running."""

  def __init__(self):
    super().__init__()
    self._result_lock = threading.Lock()
    self._result: SignerInstallResult | None = None
    self._started = False

    self._status_card = GreyBigButton("corolla RAM signer", "verifying kit")
    self._detail_card = GreyBigButton(
      "keep vehicle in Park",
      "do not drive or power off\nwhile installation is running",
    )
    self._close_button = BigButton("installation running", "please wait")
    self._close_button.set_enabled(False)
    self._close_button.set_click_callback(self.dismiss)
    self._scroller.add_widgets([self._status_card, self._detail_card, self._close_button])

  def show_event(self):
    super().show_event()
    device.set_override_interactive_timeout(180)
    if not self._started:
      self._started = True
      _set_install_active(True)
      threading.Thread(target=self._worker, name="corolla-ram-signer-mici", daemon=True).start()

  def hide_event(self):
    device.set_override_interactive_timeout(None)
    super().hide_event()

  def _back_enabled(self) -> bool:
    with self._result_lock:
      return self._result is not None

  def _worker(self) -> None:
    try:
      result = run_request_signer_install()
    except Exception as exc:
      result = SignerInstallResult(
        False,
        "RAM signer installer stopped unexpectedly",
        f"{type(exc).__name__}: {exc}. Do not drive; reboot openpilot before testing.",
      )
    with self._result_lock:
      self._result = result
    _set_install_active(False)

  def _update_state(self):
    super()._update_state()
    with self._result_lock:
      result = self._result
    if result is None:
      return

    self._status_card.set_text("signer live" if result.passed else "installation failed")
    self._status_card.set_value(result.title)
    saved = f"\nresult: {result.output_path}" if result.output_path is not None else ""
    self._detail_card.set_text("live probe passed" if result.passed else "do not drive")
    self._detail_card.set_value(f"{result.detail}{saved}")
    self._close_button.set_text("close")
    self._close_button.set_value("passed" if result.passed else "failed")
    self._close_button.set_enabled(True)


class CorollaSignerButton(BigButton):
  def __init__(self):
    icon = gui_app.texture("icons_mici/settings/vehicle.png", 64, 64)
    super().__init__("corolla RAM\nsigner", "install", icon)
    self._warning_icon = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
    self.set_visible(corolla_tss3_selected)
    self.set_enabled(can_install_corolla_signer)
    self.set_click_callback(self._request_install)

  def _request_install(self) -> None:
    if not can_install_corolla_signer():
      gui_app.push_widget(BigDialog("RAM signer unavailable", "Vehicle must be ON, in Park, stationary, and disengaged."))
      return

    check = request_signer_kit_compatibility()
    if not check.compatible:
      gui_app.push_widget(BigDialog("RAM signer kit error", check.detail))
      return

    def start_install() -> None:
      if can_install_corolla_signer():
        gui_app.push_widget(CorollaSignerInstallPage())
      else:
        gui_app.push_widget(BigDialog("RAM signer unavailable", "Vehicle state changed. Return to Park and disengage."))

    gui_app.push_widget(BigConfirmationDialog(
      "slide to install\nRAM signer",
      self._warning_icon,
      start_install,
      red=True,
    ))

  def _update_state(self):
    super()._update_state()
    if signer_install_active():
      self.set_value("installing")
    elif ui_state.started:
      self.set_value("install")
    else:
      self.set_value("vehicle must be on")
