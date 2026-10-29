#!/usr/bin/env python3
"""Summarize Corolla TSS3 signer and candidate longitudinal evidence from rlogs."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass, field
import json
import sys
from typing import Any


TRANSPORT_LOG_PREFIX = "Toyota TSS3 request plane "


@dataclass
class FrameEvidence:
  count: int = 0
  buses: Counter[int] = field(default_factory=Counter)
  lengths: Counter[int] = field(default_factory=Counter)
  byte_values: list[set[int]] = field(default_factory=list)
  first_hex: str | None = None
  last_hex: str | None = None
  first_ns: int | None = None
  last_ns: int | None = None

  def observe(self, bus: int, data: bytes, timestamp_ns: int | None = None) -> None:
    self.count += 1
    self.buses[bus] += 1
    self.lengths[len(data)] += 1
    self.first_hex = self.first_hex or data.hex()
    self.last_hex = data.hex()
    if timestamp_ns is not None:
      self.first_ns = timestamp_ns if self.first_ns is None else min(self.first_ns, timestamp_ns)
      self.last_ns = timestamp_ns if self.last_ns is None else max(self.last_ns, timestamp_ns)
    while len(self.byte_values) < len(data):
      self.byte_values.append(set())
    for index, value in enumerate(data):
      self.byte_values[index].add(value)

  def as_dict(self, start_ns: int | None = None) -> dict[str, Any]:
    changing = {
      str(index): [f"0x{value:02x}" for value in sorted(values)]
      for index, values in enumerate(self.byte_values) if len(values) > 1
    }
    return {
      "count": self.count,
      "buses": {str(bus): count for bus, count in sorted(self.buses.items())},
      "lengths": {str(length): count for length, count in sorted(self.lengths.items())},
      "first_hex": self.first_hex,
      "last_hex": self.last_hex,
      "first_offset_s": None if start_ns is None or self.first_ns is None else round((self.first_ns - start_ns) / 1e9, 6),
      "last_offset_s": None if start_ns is None or self.last_ns is None else round((self.last_ns - start_ns) / 1e9, 6),
      "changing_byte_values": changing,
    }


def _transport_log_message(raw: str) -> str | None:
  try:
    value = json.loads(raw)
  except (json.JSONDecodeError, TypeError):
    return None
  message = value.get("msg") if isinstance(value, dict) else None
  if isinstance(message, str) and TRANSPORT_LOG_PREFIX in message:
    return message[message.index(TRANSPORT_LOG_PREFIX):]
  return None


def _is_corolla_signer_fragment(data: bytes) -> bool:
  return len(data) == 8 and data[0] >> 4 in (8, 9, 10, 11)


def analyze_events(events: Iterable[Any]) -> dict[str, Any]:
  native_08a = FrameEvidence()
  native_160 = FrameEvidence()
  signer_responses = FrameEvidence()
  signer_requests = FrameEvidence()
  signer_request_tx_receipts = FrameEvidence()
  signer_request_tx_accepted_receipts = FrameEvidence()
  signer_request_tx_rejected_receipts = FrameEvidence()
  host_08a = FrameEvidence()
  bus_0_tx_receipts_08a = FrameEvidence()
  matched_host_08a_echo = FrameEvidence()
  host_payloads: Counter[bytes] = Counter()
  host_longitudinal_nonzero = 0
  signer_applications = 0
  signer_application_longitudinal_nonzero = 0
  signer_application_sequence_mismatch = 0
  signer_request_tx_accepted = 0
  signer_request_tx_rejected = 0
  host_publication_rejected = 0
  signer_application_fragments: list[bytes] = []
  transport_events: list[str] = []
  deployment: dict[str, Any] = {}
  car_params: dict[str, Any] = {}
  car_state_count = 0
  car_state_can_valid_count = 0
  car_state_can_timeout_count = 0
  car_state_block_pcm_enable_count = 0
  car_state_steer_fault_temporary_count = 0
  car_state_steer_fault_permanent_count = 0
  max_abs_speed_mps = 0.0
  gears: Counter[str] = Counter()
  car_control_count = 0
  car_control_enabled_count = 0
  car_control_lat_active_count = 0
  car_control_long_active_count = 0
  car_control_nonzero_accel_count = 0
  selfdrive_state_count = 0
  selfdrive_engageable_count = 0
  onroad_events: Counter[str] = Counter()
  panda_safety_modes: Counter[str] = Counter()
  panda_controls_allowed_count = 0
  panda_rx_checks_invalid_count = 0
  panda_faults: Counter[str] = Counter()
  panda_safety_transitions: list[tuple[int, str]] = []
  last_panda_safety_mode: str | None = None
  device_started_counts: Counter[bool] = Counter()
  device_started_transitions: list[tuple[int, bool]] = []
  last_device_started: bool | None = None
  start_ns: int | None = None
  end_ns: int | None = None

  for event in events:
    timestamp = int(event.logMonoTime)
    start_ns = timestamp if start_ns is None else min(start_ns, timestamp)
    end_ns = timestamp if end_ns is None else max(end_ns, timestamp)
    which = event.which()

    if which == "initData":
      value = event.initData
      deployment = {
        "git_commit": str(value.gitCommit),
        "git_branch": str(value.gitBranch),
        "git_remote": str(value.gitRemote),
        "dirty": bool(value.dirty),
      }
      continue
    if which == "carParams":
      value = event.carParams
      car_params = {
        "fingerprint": str(value.carFingerprint),
        "fingerprint_source": str(value.fingerprintSource),
        "fuzzy_fingerprint": bool(value.fuzzyFingerprint),
        "openpilot_longitudinal_control": bool(value.openpilotLongitudinalControl),
        "safety_configs": [
          {"model": str(config.safetyModel), "param": int(config.safetyParam)} for config in value.safetyConfigs
        ],
      }
      continue
    if which == "carState":
      value = event.carState
      car_state_count += 1
      car_state_can_valid_count += int(value.canValid)
      car_state_can_timeout_count += int(value.canTimeout)
      car_state_block_pcm_enable_count += int(value.blockPcmEnable)
      car_state_steer_fault_temporary_count += int(value.steerFaultTemporary)
      car_state_steer_fault_permanent_count += int(value.steerFaultPermanent)
      max_abs_speed_mps = max(max_abs_speed_mps, abs(float(value.vEgo)))
      gears[str(value.gearShifter)] += 1
      continue
    if which == "carControl":
      value = event.carControl
      car_control_count += 1
      car_control_enabled_count += int(value.enabled)
      car_control_lat_active_count += int(value.latActive)
      car_control_long_active_count += int(value.longActive)
      car_control_nonzero_accel_count += int(abs(float(value.actuators.accel)) > 1e-6)
      continue
    if which == "selfdriveState":
      selfdrive_state_count += 1
      selfdrive_engageable_count += int(event.selfdriveState.engageable)
      continue
    if which == "onroadEvents":
      for onroad_event in event.onroadEvents:
        onroad_events[str(onroad_event.name)] += 1
      continue
    if which == "deviceState":
      started = bool(event.deviceState.started)
      device_started_counts[started] += 1
      if started != last_device_started:
        device_started_transitions.append((timestamp, started))
        last_device_started = started
      continue
    if which == "pandaStates":
      for state in event.pandaStates:
        safety_mode = f"{state.safetyModel}:{int(state.safetyParam)}"
        panda_safety_modes[safety_mode] += 1
        if safety_mode != last_panda_safety_mode:
          panda_safety_transitions.append((timestamp, safety_mode))
          last_panda_safety_mode = safety_mode
        panda_controls_allowed_count += int(state.controlsAllowed)
        panda_rx_checks_invalid_count += int(state.safetyRxChecksInvalid)
        for fault in state.faults:
          panda_faults[str(fault)] += 1
      continue

    if which in ("logMessage", "errorLogMessage"):
      message = _transport_log_message(str(getattr(event, which)))
      if message is not None:
        transport_events.append(message)
      continue
    if which not in ("can", "sendcan"):
      continue

    frames = getattr(event, which)
    for frame in frames:
      address, bus, data = int(frame.address), int(frame.src), bytes(frame.dat)
      if which == "sendcan":
        if address == 0x777:
          if not _is_corolla_signer_fragment(data):
            signer_application_fragments = []
            continue
          signer_requests.observe(bus, data, timestamp)
          fragment = data[0] >> 4
          expected_fragment = 8 + len(signer_application_fragments)
          if fragment == 8:
            signer_application_fragments = [data]
          elif signer_application_fragments and fragment == expected_fragment:
            signer_application_fragments.append(data)
          else:
            signer_application_fragments = []

          if len(signer_application_fragments) == 4:
            headers = [fragment[0] for fragment in signer_application_fragments]
            if ((headers[0] & 0x0F) == (headers[2] & 0x0F) and
                (headers[1] & 0x0F) == (headers[3] & 0x0F)):
              application = b"".join(fragment[1:] for fragment in signer_application_fragments)
              carrier_sequence = (headers[0] & 0x0F) | ((headers[1] & 0x0F) << 4)
              signer_applications += 1
              if application[8:10] != b"\0\0" or application[11:13] != b"\0\0":
                signer_application_longitudinal_nonzero += 1
              if application[26] != (carrier_sequence & 0x3F):
                signer_application_sequence_mismatch += 1
            signer_application_fragments = []
        elif address == 0x08A:
          host_08a.observe(bus, data, timestamp)
          host_payloads[data] += 1
          if len(data) >= 13 and (data[8:10] != b"\0\0" or data[11:13] != b"\0\0"):
            host_longitudinal_nonzero += 1
        continue

      if bus < 0x80:
        if address == 0x08A:
          native_08a.observe(bus, data, timestamp)
        elif address == 0x160:
          native_160.observe(bus, data, timestamp)
        elif address == 0x7A9:
          signer_responses.observe(bus, data, timestamp)
      else:
        if address == 0x777 and _is_corolla_signer_fragment(data):
          signer_request_tx_receipts.observe(bus, data, timestamp)
          signer_request_tx_accepted += int(bus == 0x80)
          signer_request_tx_rejected += int(bus == 0xC0)
          if bus == 0x80:
            signer_request_tx_accepted_receipts.observe(bus, data, timestamp)
          elif bus == 0xC0:
            signer_request_tx_rejected_receipts.observe(bus, data, timestamp)
        elif address == 0x08A:
          bus_0_tx_receipts_08a.observe(bus, data, timestamp)
          # Forwarded native 0x08A traffic also creates bus-0 TX receipts. Only
          # call a receipt a host acceptance when its complete payload matches a
          # frame observed on sendcan during this route.
          if host_payloads[data] > 0 and bus in (0x80, 0xC0):
            if bus == 0x80:
              matched_host_08a_echo.observe(bus, data, timestamp)
            else:
              host_publication_rejected += 1
            host_payloads[data] -= 1

  duration_s = 0.0 if start_ns is None or end_ns is None else round((end_ns - start_ns) / 1e9, 3)
  return {
    "schema": "corolla-tss3-route-evidence-v3",
    "duration_s": duration_s,
    "deployment": deployment,
    "vehicle": {
      "car_params": car_params,
      "car_state_count": car_state_count,
      "can_valid_count": car_state_can_valid_count,
      "can_timeout_count": car_state_can_timeout_count,
      "block_pcm_enable_count": car_state_block_pcm_enable_count,
      "steer_fault_temporary_count": car_state_steer_fault_temporary_count,
      "steer_fault_permanent_count": car_state_steer_fault_permanent_count,
      "max_abs_speed_mps": round(max_abs_speed_mps, 6),
      "gears": dict(sorted(gears.items())),
      "onroad_events": dict(sorted(onroad_events.items())),
    },
    "control": {
      "car_control_count": car_control_count,
      "enabled_count": car_control_enabled_count,
      "lat_active_count": car_control_lat_active_count,
      "long_active_count": car_control_long_active_count,
      "nonzero_actuator_accel_count": car_control_nonzero_accel_count,
      "selfdrive_state_count": selfdrive_state_count,
      "selfdrive_engageable_count": selfdrive_engageable_count,
      "device_started_counts": {
        "true": device_started_counts[True],
        "false": device_started_counts[False],
      },
      "device_started_transitions": [
        {
          "offset_s": None if start_ns is None else round((timestamp - start_ns) / 1e9, 6),
          "started": started,
        }
        for timestamp, started in device_started_transitions
      ],
      "panda_safety_modes": dict(sorted(panda_safety_modes.items())),
      "panda_safety_transitions": [
        {
          "offset_s": None if start_ns is None else round((timestamp - start_ns) / 1e9, 6),
          "mode": mode,
        }
        for timestamp, mode in panda_safety_transitions
      ],
      "panda_controls_allowed_count": panda_controls_allowed_count,
      "panda_rx_checks_invalid_count": panda_rx_checks_invalid_count,
      "panda_faults": dict(sorted(panda_faults.items())),
    },
    "signer": {
      "requests_0x777": signer_requests.as_dict(start_ns),
      "request_tx_receipts_0x777": signer_request_tx_receipts.as_dict(start_ns),
      "request_tx_accepted_receipts_0x777": signer_request_tx_accepted_receipts.as_dict(start_ns),
      "request_tx_rejected_receipts_0x777": signer_request_tx_rejected_receipts.as_dict(start_ns),
      "request_tx_accepted_count": signer_request_tx_accepted,
      "request_tx_rejected_count": signer_request_tx_rejected,
      "complete_request_applications": signer_applications,
      "request_application_longitudinal_nonzero_count": signer_application_longitudinal_nonzero,
      "request_application_sequence_mismatch_count": signer_application_sequence_mismatch,
      "responses_0x7a9": signer_responses.as_dict(start_ns),
      "host_publications_0x08a": host_08a.as_dict(start_ns),
      "bus_0_tx_receipts_0x08a": bus_0_tx_receipts_08a.as_dict(start_ns),
      "matched_host_publication_echoes_0x08a": matched_host_08a_echo.as_dict(start_ns),
      "host_publication_accepted_count": matched_host_08a_echo.count,
      "host_publication_rejected_count": host_publication_rejected,
      "host_longitudinal_nonzero_count": host_longitudinal_nonzero,
      "transport_log_events": transport_events,
    },
    "native_candidates": {
      "0x08a": native_08a.as_dict(start_ns),
      "0x160": native_160.as_dict(start_ns),
    },
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("route_or_rlog", nargs="+", help="route identifier or local rlog.zst/rlog.bz2 path")
  parser.add_argument("--output", help="write JSON here instead of stdout")
  args = parser.parse_args()

  try:
    from openpilot.tools.lib.logreader import LogReader
    report = analyze_events(LogReader(args.route_or_rlog, sort_by_time=True))
  except (ImportError, OSError, ValueError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 1

  rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
  if args.output:
    from pathlib import Path
    Path(args.output).write_text(rendered, encoding="utf-8")
  else:
    print(rendered, end="")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
