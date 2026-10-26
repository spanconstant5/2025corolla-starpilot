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
  assert result["schema"] == "corolla-tss3-route-evidence-v2"
  assert result["signer"]["requests_0x777"]["count"] == 4
  assert result["signer"]["request_tx_receipts_0x777"]["count"] == 1
  assert result["signer"]["request_tx_accepted_count"] == 1
  assert result["signer"]["request_tx_rejected_count"] == 0
  assert result["signer"]["complete_request_applications"] == 1
  assert result["signer"]["request_application_longitudinal_nonzero_count"] == 0
  assert result["signer"]["request_application_sequence_mismatch_count"] == 0
  assert result["signer"]["responses_0x7a9"]["count"] == 1
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
