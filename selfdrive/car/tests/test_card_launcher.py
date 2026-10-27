from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys


MODULE_PATH = Path(__file__).parents[1] / "card_launcher.py"


def _load_launcher(tmp_path: Path, monkeypatch, params):
  request_path = tmp_path / "request"
  ready_path = tmp_path / "ready"
  request_path.write_text("bridge-token\n", encoding="utf-8")

  messaging = ModuleType("cereal.messaging")
  messaging.sub_sock = lambda *args, **kwargs: ("can-socket", args, kwargs)
  messaging.PubMaster = lambda services: ("pub-master", tuple(services))
  cereal = ModuleType("cereal")
  cereal.messaging = messaging

  params_module = ModuleType("openpilot.common.params")
  params_module.Params = lambda: params

  signer_module = ModuleType("openpilot.selfdrive.car.toyota_tss3_request_signer")
  signer_module.TSS3_SIGNER_STARTUP_BRIDGE_PARAM = "Tss3SignerStartupBridge"
  signer_module.TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH = request_path
  signer_module.TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH = ready_path

  monkeypatch.setitem(sys.modules, "cereal", cereal)
  monkeypatch.setitem(sys.modules, "cereal.messaging", messaging)
  monkeypatch.setitem(sys.modules, "openpilot.common.params", params_module)
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.car.toyota_tss3_request_signer", signer_module)

  spec = importlib.util.spec_from_file_location("card_launcher_under_test", MODULE_PATH)
  assert spec is not None and spec.loader is not None
  launcher = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(launcher)
  monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
  return launcher, ready_path


def test_launcher_binds_sockets_offroad_then_imports_card_onroad(tmp_path, monkeypatch):
  class FakeParams:
    onroad_checks = 0

    def get_bool(self, key):
      if key == "Tss3SignerStartupBridge":
        return True
      assert key == "IsOnroad"
      self.onroad_checks += 1
      return self.onroad_checks >= 2

  launcher, ready_path = _load_launcher(tmp_path, monkeypatch, FakeParams())
  calls = []
  realtime = ModuleType("openpilot.common.realtime")
  realtime.Priority = SimpleNamespace(CTRL_HIGH="ctrl-high")
  realtime.config_realtime_process = lambda core, priority: calls.append(("realtime", core, priority))
  card_module = ModuleType("openpilot.selfdrive.car.card")

  class FakeCar:
    def __init__(self, **kwargs):
      calls.append(("card", kwargs))

    def card_thread(self):
      calls.append(("card_thread",))

  card_module.Car = FakeCar
  monkeypatch.setitem(sys.modules, "openpilot.common.realtime", realtime)
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.car.card", card_module)

  launcher.main()

  assert ready_path.read_text(encoding="utf-8") == "bridge-token\n"
  assert calls[0] == ("realtime", 4, "ctrl-high")
  assert calls[1][0] == "card"
  assert calls[1][1]["can_sock"][0] == "can-socket"
  assert calls[1][1]["pm"][0] == "pub-master"
  assert calls[2] == ("card_thread",)


def test_launcher_exits_offroad_when_bridge_is_cancelled(tmp_path, monkeypatch):
  class FakeParams:
    bridge_checks = 0

    def get_bool(self, key):
      if key == "Tss3SignerStartupBridge":
        self.bridge_checks += 1
        return self.bridge_checks == 1
      assert key == "IsOnroad"
      return False

  launcher, ready_path = _load_launcher(tmp_path, monkeypatch, FakeParams())

  launcher.main()

  assert ready_path.read_text(encoding="utf-8") == "bridge-token\n"
  assert "openpilot.selfdrive.car.card" not in sys.modules
