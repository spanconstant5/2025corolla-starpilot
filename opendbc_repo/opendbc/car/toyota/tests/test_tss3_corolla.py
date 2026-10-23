"""Corolla live evidence and known answers for the shared TSS3 signer path."""
import unittest

from opendbc.can import CANDefine, CANParser
from opendbc.car import CanData, structs
from opendbc.can import CANPacker
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.tss3 import COROLLA_ORACLE_PROFILE, build_host_application, build_oracle_transport
from opendbc.car.toyota.values import CAR, ToyotaSafetyFlags


SPAN_FRAMES = {
  0x00F: bytes.fromhex("162d0040d8a0a606"),
  0x025: bytes.fromhex("0ff800005fff0092000000000000000000000000000000000000000091f9fcc0"),
  0x030: bytes.fromhex("0a000000220450b80b002000380006d4020c00000038033b00000000706253c1"),
  0x08A: bytes.fromhex("000000008000001203260003267fff007fffff3600000000000039009064215b"),
  0x0AA: bytes.fromhex("1abd1a6f1aba1a6f"),
  0x101: bytes.fromhex("8800003a000000cc"),
  0x116: bytes.fromhex("000200007a353eaa"),
  0x127: bytes.fromhex("001000000738d857"),
  0x176: bytes.fromhex("8800000000000007"),
  0x251: bytes.fromhex("a00000488068a080"),
  0x614: bytes.fromhex("000036300000ef04"),
  0x620: bytes.fromhex("0000000080000000"),
}

ALBINO_GEAR = {
  "P": bytes.fromhex("8000010074d0de47"),
  "R": bytes.fromhex("400001006f306582"),
  "D": bytes.fromhex("100001005fc18f5f"),
}


class TestToyotaTss3SharedDbc(unittest.TestCase):
  def test_corolla_params_select_live_signer_transport(self):
    # The torque-data lookup crashed card before it could publish CarParams.
    cp = CarInterface.get_non_essential_params(CAR.TOYOTA_COROLLA_TSS3)
    self.assertGreater(cp.maxLateralAccel, 0)
    self.assertFalse(cp.dashcamOnly)
    self.assertFalse(cp.openpilotLongitudinalControl)
    self.assertAlmostEqual(cp.wheelbase, 2.70)
    self.assertAlmostEqual(cp.steerRatio, 13.9, places=5)
    self.assertEqual(cp.safetyConfigs[0].safetyModel, structs.CarParams.SafetyModel.toyota)
    self.assertTrue(cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_SIGNER)
    self.assertTrue(cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_08A_HOST)
    self.assertTrue(cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_COROLLA_SIGNER)

  def test_corolla_inactive_application_matches_live_known_answer(self):
    packer = CANPacker("toyota_tss3_pt_generated")
    application = build_host_application(
      packer,
      lat_active=False,
      target_angle_raw=0,
      long_active=False,
      accel=0.0,
      set_speed_kph=0.0,
      request_sequence=1,
    )
    self.assertEqual(application.hex(), "0000000880002d4700000000007fff007fff0000c000100032000100")
    self.assertEqual(
      [msg.dat.hex() for msg in build_oracle_transport(1, application, COROLLA_ORACLE_PROFILE)],
      ["810000000880002d", "904700000000007f", "a1ff007fff0000c0", "b000100032000100"],
    )

  def test_retained_corolla_state_decodes_with_shared_dbc(self):
    parser = CANParser("toyota_tss3_pt_generated", [(address, 0) for address in (0x025, 0x030, 0x101, 0x116, 0x127)], 1)
    parser.update([(1_000_000_000, [CanData(a, d, 1) for a, d in SPAN_FRAMES.items()])])
    angle = parser.vl["STEER_ANGLE_SENSOR"]
    self.assertAlmostEqual(angle["STEER_ANGLE"] + angle["STEER_FRACTION"], -11.5)
    self.assertAlmostEqual(angle["STEER_RATE"], -1.0)
    torque = parser.vl["TSS3_EPS_TELEMETRY"]
    self.assertAlmostEqual(torque["STEERING_WHEEL_TORQUE_COARSE"] + torque["STEERING_WHEEL_TORQUE_FINE"], 1.06)
    self.assertTrue(parser.vl["BRAKE_MODULE"]["BRAKE_PRESSED"])
    self.assertGreater(parser.vl["GAS_PEDAL"]["GAS_PEDAL_USER"], 0)

  def test_retained_corolla_nonhybrid_gear_evidence(self):
    parser = CANParser("toyota_tss3_pt_generated", [("TSS3_GEAR_PACKET", 0)], 1)
    names = CANDefine("toyota_tss3_pt_generated").dv["TSS3_GEAR_PACKET"]["GEAR"]
    for i, (expected, data) in enumerate(ALBINO_GEAR.items()):
      parser.update([(1_000_000_000 + i * 10_000_000, [CanData(0x3BF, data, 1)])])
      self.assertEqual(names[int(parser.vl["TSS3_GEAR_PACKET"]["GEAR"])], expected)
