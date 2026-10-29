from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).parents[3]
LAUNCH_SCRIPT = ROOT / "launch_chffrplus.sh"
PANDAD_BINARY = ROOT / "selfdrive/pandad/pandad"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    ["git", "-C", str(ROOT), *args],
    check=check,
    capture_output=True,
    text=True,
  )


def test_prebuilt_marker_is_the_only_build_gate():
  script = LAUNCH_SCRIPT.read_text()

  assert "UsePrebuilt" not in script
  assert "prebuilt_runtime_compatible" not in script
  assert len(re.findall(r"\./build\.py", script)) == 1
  assert re.search(r'if \[ ! -f "\$DIR/prebuilt" \]; then\s+sp_launch_timing "build_start"\s+\./build\.py', script)


def test_prebuilt_pandad_is_not_older_than_its_transport_sources():
  if not (ROOT / "prebuilt").is_file() or not (ROOT / ".git").exists():
    pytest.skip("tracked prebuilt policy requires a git checkout")

  binary_path = str(PANDAD_BINARY.relative_to(ROOT))
  binary_dirty = (
    _git("diff", "--quiet", "--", binary_path, check=False).returncode != 0 or
    _git("diff", "--cached", "--quiet", "--", binary_path, check=False).returncode != 0
  )
  if binary_dirty:
    pytest.skip("pandad is being rebuilt in the working tree")

  source_paths = [
    "SConstruct",
    "selfdrive/pandad/SConscript",
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "selfdrive/pandad").glob("*.cc")),
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "selfdrive/pandad").glob("*.h")),
  ]
  source_commit = _git("log", "-1", "--format=%H", "--", *source_paths).stdout.strip()
  binary_commit = _git("log", "-1", "--format=%H", "--", binary_path).stdout.strip()

  assert source_commit and binary_commit
  assert _git("merge-base", "--is-ancestor", source_commit, binary_commit, check=False).returncode == 0, (
    f"tracked {binary_path} is older than its transport sources; rebuild and commit it before deploying prebuilt"
  )
