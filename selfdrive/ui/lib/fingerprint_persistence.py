def should_persist_detected_fingerprint(car_fingerprint: str) -> bool:
  """Keep an established vehicle identity when FPv1 temporarily returns MOCK."""
  return bool(car_fingerprint and car_fingerprint != "MOCK")
