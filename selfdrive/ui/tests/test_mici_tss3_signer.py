from types import SimpleNamespace

from cereal import car
from openpilot.selfdrive.ui.mici.layouts.settings import tss3_signer


class FakeParams:
  def __init__(self, model: str):
    self.model = model

  def get(self, key: str, **_kwargs):
    return self.model if key == "CarModel" else None


def fake_ui_state(model: str, *, started: bool = True, engaged: bool = False,
                  standstill: bool = True, gear=car.CarState.GearShifter.park):
  return SimpleNamespace(
    params=FakeParams(model),
    started=started,
    engaged=engaged,
    sm={"carState": SimpleNamespace(standstill=standstill, gearShifter=gear)},
  )


def test_mici_signer_requires_exact_corolla_model(monkeypatch):
  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state("TOYOTA_CAMRY_TSS3"))
  monkeypatch.setattr(tss3_signer, "_install_active", False)
  assert not tss3_signer.corolla_tss3_selected()
  assert not tss3_signer.can_install_corolla_signer()


def test_mici_signer_requires_on_park_stationary_and_disengaged(monkeypatch):
  monkeypatch.setattr(tss3_signer, "_install_active", False)
  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state(tss3_signer.COROLLA_TSS3_MODEL))
  assert tss3_signer.can_install_corolla_signer()

  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state(tss3_signer.COROLLA_TSS3_MODEL, started=False))
  assert not tss3_signer.can_install_corolla_signer()
  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state(tss3_signer.COROLLA_TSS3_MODEL, engaged=True))
  assert not tss3_signer.can_install_corolla_signer()
  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state(tss3_signer.COROLLA_TSS3_MODEL, standstill=False))
  assert not tss3_signer.can_install_corolla_signer()
  monkeypatch.setattr(tss3_signer, "ui_state", fake_ui_state(
    tss3_signer.COROLLA_TSS3_MODEL, gear=car.CarState.GearShifter.drive))
  assert not tss3_signer.can_install_corolla_signer()
