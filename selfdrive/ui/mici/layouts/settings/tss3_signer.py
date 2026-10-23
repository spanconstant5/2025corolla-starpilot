from __future__ import annotations

import threading

from openpilot.selfdrive.car.toyota_tss3_request_signer import request_signer_kit_compatibility
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.tss3_signer_runner import STAGE_LABELS, Tss3SignerRunner
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


COROLLA_TSS3_MODEL = "TOYOTA_COROLLA_TSS3"
_state_lock = threading.Lock()
_bringup_active = False


def corolla_tss3_selected() -> bool:
  return ui_state.params.get("CarModel", encoding="utf-8") == COROLLA_TSS3_MODEL


def signer_bringup_active() -> bool:
  with _state_lock:
    return _bringup_active


def signer_install_active() -> bool:
  # Compatibility name retained for existing callers.
  return signer_bringup_active()


def _set_bringup_active(active: bool) -> None:
  global _bringup_active
  with _state_lock:
    _bringup_active = active


def can_install_corolla_signer() -> bool:
  """The guided catcher must be armed while the vehicle is OFF/not READY."""
  return bool(corolla_tss3_selected() and not signer_bringup_active() and not ui_state.engaged and not ui_state.started)


class CorollaSignerBringupPage(NavScroller):
  """Comma 4 page for the NRTD-to-READY EPS startup race and RAM install."""

  def __init__(self):
    super().__init__()
    self._runner = Tss3SignerRunner()

    self._status_card = GreyBigButton("corolla RAM signer", "preparing startup catcher")
    self._progress_card = GreyBigButton("progress", "0%\nstarting")
    self._contract_card = GreyBigButton(
      "RAM-only startup path",
      "wait for the armed message\nthen press brake + POWER normally\nkeep the vehicle in Park",
    )
    self._action_button = BigButton("cancel bringup", "cooperative before PROGRAMMING")
    self._action_button.set_click_callback(self.dismiss)
    self._scroller.add_widgets([
      self._status_card,
      self._progress_card,
      self._contract_card,
      self._action_button,
    ])

  def show_event(self):
    super().show_event()
    _set_bringup_active(True)
    device.set_override_interactive_timeout(300)

  def hide_event(self):
    _set_bringup_active(False)
    device.set_override_interactive_timeout(None)
    self._runner.request_cancel()
    super().hide_event()

  def _update_state(self):
    super()._update_state()
    status = self._runner.snapshot()
    stage = status["stage"]
    progress = status["progress"]

    self._status_card.set_text(status["title"])
    self._status_card.set_value(status["detail"])
    self._progress_card.set_value(f"{progress}%\n{STAGE_LABELS.get(stage, stage)}")

    if status["done"]:
      self._action_button.set_text("close")
      self._action_button.set_value("signer live; safety restored")
    elif status["error"] and status.get("signer_installed"):
      self._action_button.set_text("close")
      self._action_button.set_value("installed — verification incomplete; do not drive")
    elif status["error"]:
      self._action_button.set_text("close")
      self._action_button.set_value("failed — do not drive")
    elif stage in ("arming", "armed"):
      self._action_button.set_text("cancel bringup")
      self._action_button.set_value("cooperative before PROGRAMMING")
    else:
      self._action_button.set_text("close")
      self._action_button.set_value("bringup continues safely in background")


# Compatibility alias for imports from the first UI implementation.
CorollaSignerInstallPage = CorollaSignerBringupPage


class CorollaSignerButton(BigButton):
  def __init__(self):
    icon = gui_app.texture("icons_mici/settings/vehicle.png", 64, 64)
    super().__init__("corolla RAM\nsigner", "arm", icon)
    self._warning_icon = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
    self.set_visible(corolla_tss3_selected)
    self.set_enabled(can_install_corolla_signer)
    self.set_click_callback(self._request_install)

  def _request_install(self) -> None:
    if not can_install_corolla_signer():
      gui_app.push_widget(BigDialog(
        "RAM signer unavailable",
        "Vehicle must be fully OFF/not READY, in Park, and openpilot disengaged.",
      ))
      return

    check = request_signer_kit_compatibility()
    if not check.compatible:
      gui_app.push_widget(BigDialog("RAM signer kit error", check.detail))
      return

    def start_bringup() -> None:
      if can_install_corolla_signer():
        gui_app.push_widget(CorollaSignerBringupPage())
      else:
        gui_app.push_widget(BigDialog(
          "RAM signer unavailable",
          "Vehicle state changed. Return to fully OFF/not READY before arming.",
        ))

    gui_app.push_widget(BigConfirmationDialog(
      "slide to arm\nRAM signer",
      self._warning_icon,
      start_bringup,
      red=True,
    ))

  def _update_state(self):
    super()._update_state()
    if signer_bringup_active():
      self.set_value("running")
    elif ui_state.started:
      self.set_value("power off first")
    else:
      self.set_value("arm")
