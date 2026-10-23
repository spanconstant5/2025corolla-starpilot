#!/usr/bin/env python3
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.toyota.values import CAR, EPS_SCALE, ToyotaSafetyFlags
from opendbc.safety.tests.libsafety import libsafety_py


class TestToyotaTss3CorollaSigner(unittest.TestCase):
  TX_MSGS = [[0x777, 0], [0x08A, 0]]

  def setUp(self):
    self.safety = libsafety_py.libsafety
    param = (EPS_SCALE[CAR.TOYOTA_COROLLA_TSS3] |
             ToyotaSafetyFlags.TSS3_SIGNER | ToyotaSafetyFlags.TSS3_08A_HOST |
             ToyotaSafetyFlags.TSS3_COROLLA_SIGNER)
    self.assertEqual(self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, param), 0)
    self.safety.init_tests()

  @staticmethod
  def admin(arm: bool):
    return libsafety_py.make_CANPacket(0x777, 0, bytes((7, 0xC9, 0xA8, int(arm), 0, 0, 0, 0)))

  @staticmethod
  def host_application(*, active: bool = False, angle_raw: int = 0, accel_raw: int = 0):
    application = bytearray.fromhex("0000000880002d4700000000007fff007fff0000c000100032000100")
    application[8:10] = int(accel_raw).to_bytes(2, "big", signed=True)
    application[11:13] = int(accel_raw).to_bytes(2, "big", signed=True)
    application[18:20] = int(angle_raw).to_bytes(2, "big", signed=True)
    application[21] = 11 if active else 0
    application[24] = 100 if active else 50
    msg = libsafety_py.make_CANPacket(0x08A, 0, bytes(application) + bytes.fromhex("01234567"))
    msg[0].fd = 1
    return msg

  def engage(self):
    native = bytearray(32)
    native[3] = 0x08  # FRC operating latch, bit 27
    self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x08A, 2, bytes(native)))
    self.assertTrue(self.safety.get_controls_allowed())

  def test_exact_four_frame_header_envelope(self):
    for header in (0x81, 0x90, 0xA1, 0xB0, 0x8F, 0x9F, 0xAF, 0xBF):
      msg = libsafety_py.make_CANPacket(0x777, 0, bytes((header, 0, 0, 0, 0, 0, 0, 0)))
      self.assertTrue(self.safety.safety_tx_hook(msg), hex(header))

    for header in (0x00, 0x7F, 0xC8, 0xC9, 0xFF):
      msg = libsafety_py.make_CANPacket(0x777, 0, bytes((header, 0, 0, 0, 0, 0, 0, 0)))
      self.assertFalse(self.safety.safety_tx_hook(msg), hex(header))

  def test_signer_envelope_rejects_wrong_bus_length_and_fd(self):
    self.assertFalse(self.safety.safety_tx_hook(
      libsafety_py.make_CANPacket(0x777, 1, bytes((0x81, 0, 0, 0, 0, 0, 0, 0)))))
    self.assertFalse(self.safety.safety_tx_hook(
      libsafety_py.make_CANPacket(0x777, 0, bytes((0x81, 0, 0, 0, 0, 0, 0)))))

    fd_msg = libsafety_py.make_CANPacket(0x777, 0, bytes((0x81, 0, 0, 0, 0, 0, 0, 0)))
    fd_msg[0].fd = 1
    self.assertFalse(self.safety.safety_tx_hook(fd_msg))

    self.assertFalse(self.safety.safety_tx_hook(
      libsafety_py.make_CANPacket(0x777, 1, bytes((7, 0xC9, 0xA8, 1, 0, 0, 0, 0)))))

  def test_host_08a_requires_arm_and_keeps_longitudinal_inactive(self):
    self.assertFalse(self.safety.safety_tx_hook(self.host_application()))
    self.assertTrue(self.safety.safety_tx_hook(self.admin(True)))
    self.assertTrue(self.safety.safety_tx_hook(self.host_application()))
    self.assertFalse(self.safety.safety_tx_hook(self.host_application(accel_raw=1)))

  def test_active_lateral_is_control_gated_and_corolla_angle_bounded(self):
    self.assertTrue(self.safety.safety_tx_hook(self.admin(True)))
    self.assertFalse(self.safety.safety_tx_hook(self.host_application(active=True)))
    self.engage()
    self.assertTrue(self.safety.safety_tx_hook(self.host_application(active=True)))
    self.assertFalse(self.safety.safety_tx_hook(self.host_application(active=True, angle_raw=961)))

  def test_inactive_lateral_tracks_measured_angle(self):
    angle = bytearray(32)
    angle[1] = 1  # 1.5 degrees, which is 26 request-angle counts after scaling.
    for _ in range(6):
      self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x025, 0, bytes(angle)))

    self.assertTrue(self.safety.safety_tx_hook(self.admin(True)))
    self.assertTrue(self.safety.safety_tx_hook(self.host_application(angle_raw=26)))
    self.assertFalse(self.safety.safety_tx_hook(self.host_application(angle_raw=0)))

  def test_native_forwarding_watchdog_fails_open(self):
    self.safety.set_timer(1)
    self.assertTrue(self.safety.safety_tx_hook(self.admin(True)))
    self.assertEqual(-1, self.safety.safety_fwd_hook(2, 0x08A))
    self.safety.set_timer(100_001)
    self.assertEqual(-1, self.safety.safety_fwd_hook(2, 0x08A))
    self.safety.set_timer(100_002)
    self.assertEqual(0, self.safety.safety_fwd_hook(2, 0x08A))

  def test_release_restores_native_forwarding_and_old_160_is_blocked(self):
    self.assertTrue(self.safety.safety_tx_hook(self.admin(True)))
    self.assertEqual(-1, self.safety.safety_fwd_hook(2, 0x08A))
    self.assertTrue(self.safety.safety_tx_hook(self.admin(False)))
    self.assertEqual(0, self.safety.safety_fwd_hook(2, 0x08A))
    self.assertFalse(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(0x160, 0, bytes(32))))


if __name__ == "__main__":
  unittest.main()
