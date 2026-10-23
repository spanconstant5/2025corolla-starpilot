from opendbc.can import CANPacker
from opendbc.car import structs
from opendbc.car.toyota.e2e import apply_e2e_160, e2e_160_valid
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.toyotacan import modify_tss3_160
from opendbc.car.toyota.tss3 import COROLLA_ORACLE_PROFILE, build_host_application, build_oracle_transport
from opendbc.car.toyota.values import CAR, ToyotaSafetyFlags


def test_corolla_params_select_live_signer_transport():
  cp = CarInterface.get_non_essential_params(CAR.TOYOTA_COROLLA_TSS3)
  assert not cp.dashcamOnly
  assert not cp.openpilotLongitudinalControl
  assert cp.safetyConfigs[0].safetyModel == structs.CarParams.SafetyModel.toyota
  assert cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_SIGNER
  assert cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_08A_HOST
  assert cp.safetyConfigs[0].safetyParam & ToyotaSafetyFlags.TSS3_COROLLA_SIGNER


def test_corolla_inactive_application_matches_live_known_answer():
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
  assert application.hex() == "0000000880002d4700000000007fff007fff0000c000100032000100"
  assert [msg.dat.hex() for msg in build_oracle_transport(1, application, COROLLA_ORACLE_PROFILE)] == [
    "810000000880002d",
    "904700000000007f",
    "a1ff007fff0000c0",
    "b000100032000100",
  ]


def test_e2e_rejects_wrong_size():
  try:
    apply_e2e_160(bytes(31))
  except ValueError:
    pass
  else:
    raise AssertionError("non-32-byte 0x160 payload was accepted")


def test_modify_160_preserves_unknown_bytes_and_updates_crc():
  template = apply_e2e_160(bytes(range(32)), counter=41)
  msg = modify_tss3_160(template, -1.5, 10.0, 42)

  assert msg.address == 0x160
  assert msg.src == 0
  assert len(msg.dat) == 32
  assert msg.dat[2] == 42
  assert e2e_160_valid(msg.dat)
  assert msg.dat[4:6] == bytes((0x7A, 0x24))
  assert int.from_bytes(msg.dat[22:24], "big", signed=True) == 5377
  assert msg.dat[3] == template[3]
  assert msg.dat[6:22] == template[6:22]
  assert msg.dat[24:] == template[24:]


def test_modify_160_relay_keeps_accel_and_steer():
  template = apply_e2e_160(bytes(range(32)), counter=9)
  msg = modify_tss3_160(template, None, None, 9)
  assert msg.dat == template
