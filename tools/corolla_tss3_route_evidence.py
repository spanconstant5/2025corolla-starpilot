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

  def observe(self, bus: int, data: bytes) -> None:
    self.count += 1
    self.buses[bus] += 1
    self.lengths[len(data)] += 1
    self.first_hex = self.first_hex or data.hex()
    self.last_hex = data.hex()
    while len(self.byte_values) < len(data):
      self.byte_values.append(set())
    for index, value in enumerate(data):
      self.byte_values[index].add(value)

  def as_dict(self) -> dict[str, Any]:
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


def analyze_events(events: Iterable[Any]) -> dict[str, Any]:
  native_08a = FrameEvidence()
  native_160 = FrameEvidence()
  signer_responses = FrameEvidence()
  signer_requests = FrameEvidence()
  host_08a = FrameEvidence()
  bus_0_tx_receipts_08a = FrameEvidence()
  matched_host_08a_echo = FrameEvidence()
  host_payloads: Counter[bytes] = Counter()
  host_longitudinal_nonzero = 0
  transport_events: list[str] = []
  start_ns: int | None = None
  end_ns: int | None = None

  for event in events:
    timestamp = int(event.logMonoTime)
    start_ns = timestamp if start_ns is None else min(start_ns, timestamp)
    end_ns = timestamp if end_ns is None else max(end_ns, timestamp)
    which = event.which()

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
          signer_requests.observe(bus, data)
        elif address == 0x08A:
          host_08a.observe(bus, data)
          host_payloads[data] += 1
          if len(data) >= 13 and (data[8:10] != b"\0\0" or data[11:13] != b"\0\0"):
            host_longitudinal_nonzero += 1
        continue

      if bus < 0x80:
        if address == 0x08A:
          native_08a.observe(bus, data)
        elif address == 0x160:
          native_160.observe(bus, data)
        elif address == 0x7A9:
          signer_responses.observe(bus, data)
      elif address == 0x08A:
        bus_0_tx_receipts_08a.observe(bus, data)
        # Forwarded native 0x08A traffic also creates bus-0 TX receipts. Only
        # call a receipt a host acceptance when its complete payload matches a
        # frame observed on sendcan during this route.
        if host_payloads[data] > 0:
          matched_host_08a_echo.observe(bus, data)
          host_payloads[data] -= 1

  duration_s = 0.0 if start_ns is None or end_ns is None else round((end_ns - start_ns) / 1e9, 3)
  return {
    "schema": "corolla-tss3-route-evidence-v1",
    "duration_s": duration_s,
    "signer": {
      "requests_0x777": signer_requests.as_dict(),
      "responses_0x7a9": signer_responses.as_dict(),
      "host_publications_0x08a": host_08a.as_dict(),
      "bus_0_tx_receipts_0x08a": bus_0_tx_receipts_08a.as_dict(),
      "matched_host_publication_echoes_0x08a": matched_host_08a_echo.as_dict(),
      "host_longitudinal_nonzero_count": host_longitudinal_nonzero,
      "transport_log_events": transport_events,
    },
    "native_candidates": {
      "0x08a": native_08a.as_dict(),
      "0x160": native_160.as_dict(),
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
