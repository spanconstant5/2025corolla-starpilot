#!/usr/bin/env python3
"""Bind card messaging early without importing the full controls stack offroad."""

from __future__ import annotations

import os
import time

import cereal.messaging as messaging

from openpilot.common.params import Params
from openpilot.selfdrive.car.toyota_tss3_request_signer import (
  TSS3_SIGNER_STARTUP_BRIDGE_PARAM,
  TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH,
  TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH,
)


CARD_PUBLISH_SERVICES = ['sendcan', 'carState', 'carParams', 'carOutput', 'liveTracks', 'starpilotCarControl']


def _bridge_request_token() -> str | None:
  try:
    token = TSS3_SIGNER_STARTUP_BRIDGE_REQUEST_PATH.read_text(encoding="utf-8").strip()
    return token or None
  except OSError:
    return None


def _publish_bridge_ready(token: str) -> None:
  temporary = TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH.with_name(
    f".{TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH.name}.{os.getpid()}",
  )
  temporary.write_text(token + "\n", encoding="utf-8")
  os.replace(temporary, TSS3_SIGNER_STARTUP_BRIDGE_READY_PATH)


def main() -> None:
  params = Params()

  # These are the only objects needed before the installer takes its direct
  # Panda lease. Keeping the publisher bound lets native pandad's sendcan
  # subscriber finish connecting before card can issue sequence 1.
  can_sock = messaging.sub_sock('can', timeout=20)
  pm = messaging.PubMaster(CARD_PUBLISH_SERVICES)

  if params.get_bool(TSS3_SIGNER_STARTUP_BRIDGE_PARAM):
    token = _bridge_request_token()
    if token is not None:
      _publish_bridge_ready(token)

    while params.get_bool(TSS3_SIGNER_STARTUP_BRIDGE_PARAM) and not params.get_bool("IsOnroad"):
      time.sleep(0.02)

  if not params.get_bool("IsOnroad"):
    return

  # Heavy imports and realtime configuration remain strictly onroad.
  from openpilot.common.realtime import Priority, config_realtime_process
  from openpilot.selfdrive.car.card import Car

  config_realtime_process(4, Priority.CTRL_HIGH)
  Car(can_sock=can_sock, pm=pm).card_thread()


if __name__ == "__main__":
  main()
