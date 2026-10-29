import json
from types import SimpleNamespace

from openpilot.tools.corolla_tss3_route_evidence import analyze_events


class Event(SimpleNamespace):
  def which(self):
    return self.kind


def can_frame(address, src, data):
  return SimpleNamespace(address=address, src=src, dat=data)


def test_route_evidence_separates_native_signer_and_host_traffic():
  inactive = bytes.fromhex("0000000880002d4700000000007fff007fff0000c000100032000100")
  signed = inactive + bytes.fromhex("7defe3ef")
  events = [
    Event(kind="can", logMonoTime=1_000_000_000, can=[can_frame(0x08A, 2, bytes(32))]),
    Event(kind="sendcan", logMonoTime=1_001_000_000, sendcan=[
      can_frame(0x777, 0, bytes.fromhex("810000000880002d")),
      can_frame(0x777, 0, bytes.fromhex("904700000000007f")),
      can_frame(0x777, 0, bytes.fromhex("a1ff007fff0000c0")),
      can_frame(0x777, 0, bytes.fromhex("b000100032000100")),
      can_frame(0x08A, 0, signed),
    ]),
    Event(kind="can", logMonoTime=1_002_000_000, can=[
      can_frame(0x7A9, 0, bytes.fromhex("c90100fe7defe3ef")),
      can_frame(0x777, 0x80, bytes.fromhex("810000000880002d")),
      can_frame(0x08A, 0x80, signed),
      can_frame(0x160, 1, bytes(32)),
    ]),
    Event(kind="logMessage", logMonoTime=1_003_000_000, logMessage=json.dumps({
      "msg": "Toyota TSS3 request plane host_08a_active: {}",
    })),
  ]

  result = analyze_events(events)
  assert result["duration_s"] == 0.003
  assert result["schema"] == "corolla-tss3-route-evidence-v3"
  assert result["signer"]["requests_0x777"]["count"] == 4
  assert result["signer"]["request_tx_receipts_0x777"]["count"] == 1
  assert result["signer"]["request_tx_accepted_count"] == 1
  assert result["signer"]["request_tx_rejected_count"] == 0
  assert result["signer"]["complete_request_applications"] == 1
  assert result["signer"]["request_application_longitudinal_nonzero_count"] == 0
  assert result["signer"]["request_application_sequence_mismatch_count"] == 0
  assert result["signer"]["responses_0x7a9"]["count"] == 1
  assert result["signer"]["responses_0x7a9"]["first_offset_s"] == 0.002
  assert result["signer"]["responses_0x7a9"]["last_offset_s"] == 0.002
  assert result["signer"]["host_publications_0x08a"]["count"] == 1
  assert result["signer"]["bus_0_tx_receipts_0x08a"]["count"] == 1
  assert result["signer"]["matched_host_publication_echoes_0x08a"]["count"] == 1
  assert result["signer"]["host_publication_accepted_count"] == 1
  assert result["signer"]["host_publication_rejected_count"] == 0
  assert result["signer"]["host_longitudinal_nonzero_count"] == 0
  assert result["native_candidates"]["0x08a"]["buses"] == {"2": 1}
  assert result["native_candidates"]["0x160"]["buses"] == {"1": 1}
  assert result["signer"]["transport_log_events"] == [
    "Toyota TSS3 request plane host_08a_active: {}",
  ]
  assert result["deployment"] == {}
  assert result["vehicle"]["car_state_count"] == 0
  assert result["control"]["long_active_count"] == 0


def test_route_evidence_detects_carrier_application_sequence_mismatch():
  events = [Event(kind="sendcan", logMonoTime=1_000_000_000, sendcan=[
    can_frame(0x777, 0, bytes.fromhex("810000000880002d")),
    can_frame(0x777, 0, bytes.fromhex("904700000000007f")),
    can_frame(0x777, 0, bytes.fromhex("a1ff007fff0000c0")),
    can_frame(0x777, 0, bytes.fromhex("b000100032000000")),
  ])]

  result = analyze_events(events)

  assert result["signer"]["complete_request_applications"] == 1
  assert result["signer"]["request_application_sequence_mismatch_count"] == 1


def test_route_evidence_records_deployment_vehicle_and_safety_gates():
  events = [
    Event(kind="initData", logMonoTime=1_000_000_000, initData=SimpleNamespace(
      gitCommit="abc123", gitBranch="star2025", gitRemote="https://example.test/openpilot.git", dirty=False,
    )),
    Event(kind="carParams", logMonoTime=1_001_000_000, carParams=SimpleNamespace(
      carFingerprint="TOYOTA_COROLLA_TSS3", fingerprintSource="can", fuzzyFingerprint=False,
      openpilotLongitudinalControl=False,
      safetyConfigs=[SimpleNamespace(safetyModel="toyota", safetyParam=53321)],
    )),
    Event(kind="carState", logMonoTime=1_002_000_000, carState=SimpleNamespace(
      canValid=True, canTimeout=False, blockPcmEnable=True, steerFaultTemporary=True,
      steerFaultPermanent=False, vEgo=0.0, gearShifter="park",
    )),
    Event(kind="carControl", logMonoTime=1_003_000_000, carControl=SimpleNamespace(
      enabled=False, latActive=False, longActive=False, actuators=SimpleNamespace(accel=0.0),
    )),
    Event(kind="selfdriveState", logMonoTime=1_004_000_000,
          selfdriveState=SimpleNamespace(engageable=False)),
    Event(kind="onroadEvents", logMonoTime=1_005_000_000,
          onroadEvents=[SimpleNamespace(name="wrongGear")]),
    Event(kind="pandaStates", logMonoTime=1_006_000_000, pandaStates=[SimpleNamespace(
      safetyModel="toyota", safetyParam=53321, controlsAllowed=False,
      safetyRxChecksInvalid=False, faults=[],
    )]),
  ]

  result = analyze_events(events)

  assert result["deployment"] == {
    "git_commit": "abc123",
    "git_branch": "star2025",
    "git_remote": "https://example.test/openpilot.git",
    "dirty": False,
  }
  assert result["vehicle"]["car_params"]["fingerprint"] == "TOYOTA_COROLLA_TSS3"
  assert result["vehicle"]["car_params"]["openpilot_longitudinal_control"] is False
  assert result["vehicle"]["gears"] == {"park": 1}
  assert result["vehicle"]["onroad_events"] == {"wrongGear": 1}
  assert result["control"]["long_active_count"] == 0
  assert result["control"]["nonzero_actuator_accel_count"] == 0
  assert result["control"]["panda_safety_modes"] == {"toyota:53321": 1}
  assert result["control"]["panda_controls_allowed_count"] == 0
  assert result["control"]["panda_rx_checks_invalid_count"] == 0
