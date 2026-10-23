"""TSS3 request construction and EPS signer transport helpers."""
from collections import deque
from dataclasses import dataclass
import json
from math import isfinite

from opendbc.car.can_definitions import CanData
from opendbc.car.carlog import carlog

TSS3_B6_TARGET_ANGLE_SCALE_DEG = 1024 / 17870
TSS3_SIGNER_CONTROL_ADDR = 0x777
TSS3_SIGNER_CONTROL_MAGIC = b"\x07\xC7\xC7"
TSS3_SIGNER_BUS = 1

TSS3_NO_LATERAL_REQUEST_ID = 0
TSS3_LTA_LCA_ID = 11
TSS3_LTA_ASSIST_GAIN_RAW = 100
TSS3_INACTIVE_ASSIST_GAIN_RAW = 50
TSS3_LONGITUDINAL_HOST_REQUEST = (0x2D, 0x47)
NATIVE_08A_ADDR = 0x08A
ADMIN_ADDR = 0x777
DOWNSTREAM_BUS = 0
ADMIN_BUS = 1
SOURCE_BUS = 2
PANDA_RETURNED_OFFSET = 0x80
PANDA_REJECTED_OFFSET = 0xC0

ORACLE_REQUEST_ADDR = 0x777
ORACLE_RESPONSE_ADDR = 0x7A9
ORACLE_BUS = 1  # kit manifest: oracle C8/C9 on bus1 (camera/body bus, same as ADMIN_BUS)
ORACLE_PRIVATE_SID = 0xC9
ORACLE_SEQUENCE_MAX = 0x1F
ORACLE_MAX_PENDING_GENERATIONS = 8
ORACLE_PUBLICATION_DEADLINE_NS = 90_000_000

ORACLE_CARRIER_C8_SIX_FRAME = "c8-six-frame"
ORACLE_CARRIER_FUNCTIONAL_NIBBLE4 = "functional-nibble4"


@dataclass(frozen=True)
class ToyotaTss3OracleProfile:
  request_bus: int
  response_bus: int
  admin_bus: int
  carrier: str
  sequence_max: int


CAMRY_ORACLE_PROFILE = ToyotaTss3OracleProfile(
  request_bus=1,
  response_bus=1,
  admin_bus=1,
  carrier=ORACLE_CARRIER_C8_SIX_FRAME,
  sequence_max=0x1F,
)

# Live Corolla 8965F1208000 evidence: four classic frames on Panda bus 0,
# followed by one C9 response on bus 0. The sequence is split across the low
# nibbles of alternating frame headers and therefore spans the full u8 range.
COROLLA_ORACLE_PROFILE = ToyotaTss3OracleProfile(
  request_bus=0,
  response_bus=0,
  admin_bus=0,
  carrier=ORACLE_CARRIER_FUNCTIONAL_NIBBLE4,
  sequence_max=0xFF,
)


def target_angle_deg_to_raw(angle_deg: float) -> int:
  return int(round(angle_deg / TSS3_B6_TARGET_ANGLE_SCALE_DEG))


def build_host_application(packer, *, lat_active: bool, target_angle_raw: int,
                           long_active: bool, accel: float,
                           set_speed_kph: float, request_sequence: int) -> bytes:
  """Build the complete comma-owned TSS3 0x08A application.

  The FRC frame is never an application template or freshness source. The
  constants below are the dominant complete Camry active and inactive
  envelopes measured across 44,613 native publications.
  """
  if not -(1 << 15) <= target_angle_raw < (1 << 15):
    raise ValueError("target angle must fit signed16")
  if not 0 <= request_sequence <= 0x3F:
    raise ValueError("request sequence must fit u6")

  accel_request = float(accel) if long_active else 0.0
  if not -32.768 <= accel_request <= 32.767:
    raise ValueError("acceleration must fit signed16 at 0.001 m/s^2")
  set_speed = max(0, min(255, int(round(set_speed_kph)))) if isfinite(set_speed_kph) else 0

  values = {
    "CRUISE_OPERATING_LATCH": 1,
    "SET_ME_X80": 0x80,
    "LONGITUDINAL_REQUEST_ID_A": TSS3_LONGITUDINAL_HOST_REQUEST[0] >> 2,
    "LONGITUDINAL_ALLOCATION_METHOD_A": TSS3_LONGITUDINAL_HOST_REQUEST[0] & 0x3,
    "LONGITUDINAL_REQUEST_ID_B": TSS3_LONGITUDINAL_HOST_REQUEST[1] >> 2,
    "LONGITUDINAL_ALLOCATION_METHOD_B": TSS3_LONGITUDINAL_HOST_REQUEST[1] & 0x3,
    "LONGITUDINAL_REQUEST_ACCEL_A": accel_request,
    "SET_SPEED": set_speed,
    "LONGITUDINAL_REQUEST_ACCEL_B": accel_request,
    "SET_ME_X7FFF_A": 0x7FFF,
    "SET_ME_X7FFF_B": 0x7FFF,
    "LATERAL_REQUEST_PINION_ANGLE": target_angle_raw * 0.001000121519,
    "SET_ME_XC0": 0xC0,
    "LATERAL_REQUEST_ID": TSS3_LTA_LCA_ID if lat_active else TSS3_NO_LATERAL_REQUEST_ID,
    "SET_ME_X10": 0x10,
    "LATERAL_ASSIST_GAIN": (TSS3_LTA_ASSIST_GAIN_RAW if lat_active else TSS3_INACTIVE_ASSIST_GAIN_RAW) * 0.01,
    "REQUEST_SEQUENCE": request_sequence,
  }
  _, data, _ = packer.make_can_msg("TSS3_CONTROL_REQUEST", DOWNSTREAM_BUS, values)
  return data[:28]


def make_request_plane_admin(arm: bool, bus: int = ADMIN_BUS) -> CanData:
  return CanData(ADMIN_ADDR, bytes((7, 0xC9, 0xA8, int(arm), 0, 0, 0, 0)), bus)


def build_oracle_transport(seq: int, application: bytes,
                           profile: ToyotaTss3OracleProfile = CAMRY_ORACLE_PROFILE) -> list[CanData]:
  """Carry one 28-byte application through the target EPS signer transport."""
  if not 1 <= seq <= profile.sequence_max:
    raise ValueError(f"oracle sequence must be 1..{profile.sequence_max}")
  if len(application) != 28:
    raise ValueError("oracle application must be exactly 28 bytes")

  if profile.carrier == ORACLE_CARRIER_C8_SIX_FRAME:
    stream = application + b"\0\0"
    return [CanData(ORACLE_REQUEST_ADDR,
                    bytes((0xC8, (fragment << 5) | seq)) + stream[fragment * 5:(fragment + 1) * 5] + b"\0",
                    profile.request_bus) for fragment in range(6)]

  if profile.carrier == ORACLE_CARRIER_FUNCTIONAL_NIBBLE4:
    low = seq & 0x0F
    high = (seq >> 4) & 0x0F
    headers = (0x80 | low, 0x90 | high, 0xA0 | low, 0xB0 | high)
    return [CanData(ORACLE_REQUEST_ADDR, bytes((header,)) + application[fragment * 7:(fragment + 1) * 7],
                    profile.request_bus) for fragment, header in enumerate(headers)]

  raise ValueError(f"unsupported oracle carrier: {profile.carrier}")


@dataclass
class SignRequest:
  sequence: int
  application: bytes
  control_epoch: int
  generation_started_ns: int
  trailer: bytes | None = None
  failed: bool = False
  superseded: bool = False


class ToyotaTss3RequestTransport:
  """Bounded 100 Hz transport for normal CarController output.

  CarController owns application cadence and actuator state. Every 10 ms control
  tick can enqueue one fresh application for the EPS signer; the EPS owns all
  SecOC freshness and returns only FV4||MAC28. A small pipeline hides signer
  round-trip latency without replaying historical control after a missing
  private response. Native 0x08A remains a liveness input to CANParser, not the
  host publication clock.
  """

  def __init__(self, packer, oracle_profile: ToyotaTss3OracleProfile = CAMRY_ORACLE_PROFILE):
    self.packer = packer
    self.oracle_profile = oracle_profile
    self.can_valid = False
    self.control_enabled = False
    self.control_lat_active = False
    self.control_target_angle_raw = 0
    self.control_long_active = False
    self.control_accel = 0.0
    self.control_set_speed_kph = 0.0
    self.control_epoch = 0
    self.control_started_ns = 0

    self.next_oracle_sequence = 1
    self.next_request_sequence = 0
    self.pending_requests: deque[SignRequest] = deque()
    self.requests_by_sequence: dict[int, SignRequest] = {}
    self.pending_sends: list[CanData] = []

    self.active = False
    self.arm_pending = False
    self.arm_host_frame: bytes | None = None
    self.last_publication_ns = 0
    self.authority_failed = False
    self.last_failure_reason = ""
    self.session_open = False
    self._reset_diagnostics()

  def _reset_diagnostics(self) -> None:
    self.requests_queued = 0
    self.responses_valid = 0
    self.responses_failed = 0
    self.responses_unmatched = 0
    self.requests_superseded = 0
    self.publications_sent = 0
    self.publications_accepted = 0
    self.publications_rejected = 0
    self.max_pending_requests = 0
    self.last_response_latency_ms: float | None = None
    self.max_response_latency_ms: float | None = None

  def diagnostic_snapshot(self) -> dict[str, object]:
    """Small route-log-safe summary for post-drive signer validation."""
    return {
      "carrier": self.oracle_profile.carrier,
      "request_bus": self.oracle_profile.request_bus,
      "response_bus": self.oracle_profile.response_bus,
      "admin_bus": self.oracle_profile.admin_bus,
      "requests_queued": self.requests_queued,
      "responses_valid": self.responses_valid,
      "responses_failed": self.responses_failed,
      "responses_unmatched": self.responses_unmatched,
      "requests_superseded": self.requests_superseded,
      "publications_sent": self.publications_sent,
      "publications_accepted": self.publications_accepted,
      "publications_rejected": self.publications_rejected,
      "max_pending_requests": self.max_pending_requests,
      "last_response_latency_ms": self.last_response_latency_ms,
      "max_response_latency_ms": self.max_response_latency_ms,
      "authority_failed": self.authority_failed,
      "last_failure_reason": self.last_failure_reason,
    }

  def _log_diagnostics(self, event: str) -> None:
    carlog.info(f"Toyota TSS3 request plane {event}: {json.dumps(self.diagnostic_snapshot(), sort_keys=True)}")

  def authority_unavailable(self) -> bool:
    return self.control_enabled and self.authority_failed

  def _record_failure(self, reason: str) -> None:
    self.last_failure_reason = reason
    carlog.error(f"Toyota TSS3 request plane failure: {reason}")

  def _remove_request(self, request: SignRequest) -> None:
    if self.requests_by_sequence.get(request.sequence) is request:
      del self.requests_by_sequence[request.sequence]

  def _prune_head(self) -> None:
    while self.pending_requests:
      request = self.pending_requests[0]
      if request.control_epoch == self.control_epoch and not request.failed and not request.superseded:
        break
      self.pending_requests.popleft()
      self._remove_request(request)

  def _invalidate_actuation(self) -> None:
    self.pending_requests.clear()
    self.requests_by_sequence.clear()

  def _release(self) -> None:
    if self.active or self.arm_pending:
      self.pending_sends.append(make_request_plane_admin(False, self.oracle_profile.admin_bus))
    self.active = False
    self.arm_pending = False
    self.arm_host_frame = None
    self.last_publication_ns = 0
    self.control_started_ns = 0
    self._invalidate_actuation()
    if self.session_open:
      self._log_diagnostics("release")
      self.session_open = False

  def _authority_failure(self, reason: str) -> None:
    if self.authority_failed:
      return
    self.authority_failed = True
    self._record_failure(reason)
    self._release()

  def _observe_tx_echo(self, address: int, data: bytes, src: int, now_ns: int) -> None:
    if address == ADMIN_ADDR and self.arm_pending and data == make_request_plane_admin(True, self.oracle_profile.admin_bus).dat:
      if src == self.oracle_profile.admin_bus + PANDA_REJECTED_OFFSET:
        self._authority_failure("arm_admin_rejected")
      return
    if address != NATIVE_08A_ADDR:
      return

    if src == DOWNSTREAM_BUS + PANDA_RETURNED_OFFSET:
      if self.arm_pending and data == self.arm_host_frame:
        self.active = True
        self.arm_pending = False
        self.arm_host_frame = None
        self.last_publication_ns = now_ns
        self.publications_accepted += 1
        self._log_diagnostics("host_08a_active")
      elif self.active:
        self.last_publication_ns = now_ns
        self.publications_accepted += 1
    elif src == DOWNSTREAM_BUS + PANDA_REJECTED_OFFSET:
      self.publications_rejected += 1
      if self.arm_pending and data == self.arm_host_frame:
        self._authority_failure("handoff_host_frame_rejected")
      elif self.active:
        carlog.warning("Toyota TSS3 request plane TX rejected")

  def _observe_oracle_response(self, data: bytes, now_ns: int) -> None:
    if len(data) != 8 or data[0] != ORACLE_PRIVATE_SID:
      return
    seq, status = data[1], data[2]
    if not 1 <= seq <= self.oracle_profile.sequence_max or data[3] != (seq ^ 0xFF):
      return

    request = self.requests_by_sequence.get(seq)
    if request is None or request.control_epoch != self.control_epoch:
      self.responses_unmatched += 1
      return
    if now_ns - request.generation_started_ns > ORACLE_PUBLICATION_DEADLINE_NS:
      if not request.superseded:
        request.superseded = True
        self.requests_superseded += 1
      return

    # The resident drains requests serially. Seeing a later response proves it
    # has already moved past every earlier request. Preserve earlier responses
    # already ready for publication, but never stall on an earlier response
    # that was lost between EPS and card.
    for older in self.pending_requests:
      if older is request:
        break
      if older.trailer is None:
        if not older.superseded:
          older.superseded = True
          self.requests_superseded += 1

    if status != 0:
      request.failed = True
      self.responses_failed += 1
      carlog.warning(f"Toyota TSS3 request plane signer status {status}")
    else:
      request.trailer = data[4:8]
      latency_ms = round((now_ns - request.generation_started_ns) / 1_000_000, 3)
      self.last_response_latency_ms = latency_ms
      self.max_response_latency_ms = latency_ms if self.max_response_latency_ms is None else max(self.max_response_latency_ms, latency_ms)
      self.responses_valid += 1
      if self.responses_valid == 1:
        self._log_diagnostics("signer_response_live")
    self._prune_head()

  def observe(self, can_packets: list[tuple[int, list[CanData]]], can_valid: bool) -> None:
    self.can_valid = bool(can_valid)
    if not self.can_valid and (self.active or self.arm_pending):
      self._authority_failure("can_invalid")

    for nanos, packets in can_packets:
      now_ns = int(nanos)
      for address, data, src in packets:
        address_i, src_i, payload = int(address), int(src), bytes(data)
        if src_i >= PANDA_RETURNED_OFFSET:
          self._observe_tx_echo(address_i, payload, src_i, now_ns)
        elif src_i == self.oracle_profile.response_bus and address_i == ORACLE_RESPONSE_ADDR:
          self._observe_oracle_response(payload, now_ns)

  def _expire(self, now_ns: int) -> None:
    self._prune_head()
    if not self.control_enabled or not self.can_valid or self.authority_failed:
      return

    reference_ns = self.last_publication_ns if self.active else self.control_started_ns
    if reference_ns and now_ns - reference_ns > ORACLE_PUBLICATION_DEADLINE_NS:
      self._authority_failure("oracle_dead")

  def _take_ready_host_frame(self) -> bytes | None:
    self._prune_head()
    if not self.pending_requests:
      return None
    request = self.pending_requests[0]
    if request.trailer is None:
      return None
    self.pending_requests.popleft()
    self._remove_request(request)
    if request.control_epoch != self.control_epoch:
      return None
    return request.application + request.trailer

  def _allocate_oracle_sequence(self) -> int | None:
    for _ in range(self.oracle_profile.sequence_max):
      seq = self.next_oracle_sequence
      self.next_oracle_sequence = (seq % self.oracle_profile.sequence_max) + 1
      if seq not in self.requests_by_sequence:
        return seq
    return None

  def _queue_signing_latest(self, now_ns: int) -> None:
    self._prune_head()
    if (not self.control_enabled or not self.can_valid or self.authority_failed or
        len(self.pending_requests) >= ORACLE_MAX_PENDING_GENERATIONS):
      return

    seq = self._allocate_oracle_sequence()
    if seq is None:
      return
    if self.control_started_ns == 0:
      self.control_started_ns = now_ns
    application = build_host_application(
      self.packer,
      lat_active=self.control_lat_active,
      target_angle_raw=self.control_target_angle_raw,
      long_active=self.control_long_active,
      accel=self.control_accel,
      set_speed_kph=self.control_set_speed_kph,
      request_sequence=self.next_request_sequence,
    )
    self.next_request_sequence = (self.next_request_sequence + 1) & 0x3F
    request = SignRequest(seq, application, self.control_epoch, now_ns)
    self.pending_requests.append(request)
    self.requests_by_sequence[seq] = request
    self.requests_queued += 1
    self.max_pending_requests = max(self.max_pending_requests, len(self.pending_requests))
    self.pending_sends.extend(build_oracle_transport(seq, application, self.oracle_profile))

  def control_generation_due(self, *, enabled: bool, lat_active: bool, long_active: bool) -> bool:
    """Whether this 100 Hz controller tick can create a new application."""
    enabled = bool(enabled)
    control_state = (enabled, bool(enabled and lat_active), bool(enabled and long_active))
    previous_state = (self.control_enabled, self.control_lat_active, self.control_long_active)
    if not enabled or not self.can_valid or self.authority_failed:
      return False
    if control_state != previous_state:
      return True

    active_pending = sum(not request.failed and not request.superseded for request in self.pending_requests)
    front_ready = bool(self.pending_requests and self.pending_requests[0].trailer is not None)
    return active_pending - int(front_ready) < ORACLE_MAX_PENDING_GENERATIONS

  def update_control(self, *, enabled: bool, lat_active: bool, target_angle_deg: float,
                     long_active: bool, accel: float, set_speed_kph: float,
                     now_nanos: int) -> list[CanData]:
    enabled = bool(enabled)
    lat_active = enabled and bool(lat_active)
    long_active = enabled and bool(long_active)
    control_state = (enabled, lat_active, long_active)
    previous_state = (self.control_enabled, self.control_lat_active, self.control_long_active)
    if control_state != previous_state:
      self.control_epoch += 1
      self._invalidate_actuation()
      if enabled and not self.control_enabled:
        self.authority_failed = False
        self.last_failure_reason = ""
        self.session_open = True
        self._reset_diagnostics()
        self.next_request_sequence = 0
        self.control_started_ns = 0
        self.last_publication_ns = 0

    self.control_enabled = enabled
    self.control_lat_active = lat_active
    self.control_target_angle_raw = target_angle_deg_to_raw(float(target_angle_deg))
    self.control_long_active = long_active
    self.control_accel = float(accel) if long_active else 0.0
    self.control_set_speed_kph = float(set_speed_kph)

    if not enabled:
      self._release()
    else:
      self._expire(now_nanos)
      if not self.authority_failed:
        # Do not send a second host frame before Panda confirms the arm frame.
        # Once active, publish at most one signed application per 10 ms control
        # tick even if multiple EPS responses arrived in the same CAN batch.
        if not self.arm_pending:
          frame = self._take_ready_host_frame()
          if frame is not None:
            if not self.active:
              self.pending_sends.append(make_request_plane_admin(True, self.oracle_profile.admin_bus))
              self.arm_pending = True
              self.arm_host_frame = frame
            self.pending_sends.append(CanData(NATIVE_08A_ADDR, frame, DOWNSTREAM_BUS))
            self.publications_sent += 1

        # Normal CarController cadence is the only publication scheduler. Keep
        # enough requests in flight to hide the EPS signer round-trip latency.
        self._queue_signing_latest(now_nanos)

    sends, self.pending_sends = self.pending_sends, []
    return sends
