from openpilot.selfdrive.ui.lib.fingerprint_persistence import should_persist_detected_fingerprint


def test_mock_fingerprint_does_not_replace_validated_model():
  assert should_persist_detected_fingerprint("TOYOTA_COROLLA_TSS3")
  assert not should_persist_detected_fingerprint("MOCK")
  assert not should_persist_detected_fingerprint("")
