"""Run the full suite in isolated, version-pinned Linux HA environments."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Install and validate each selected runtime before running all tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="all", help="HA version or all")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Home Assistant tests require Linux; use WSL on Windows")
    matrix = json.loads((ROOT / "scripts/ha-test-matrix.json").read_text())["include"]
    selected = [row for row in matrix if args.version in ("all", row["ha"])]
    if not selected:
        parser.error("Unknown version; see scripts/ha-test-matrix.json")
    uv = os.environ.get("UV", "uv")
    cache = Path(os.environ.get("HA_TEST_CACHE", Path.home() / ".cache"))
    failed = []
    for row in selected:
        version = row["ha"]
        env = cache / f"charge-tally-ha-{version}"
        python = env / "bin/python"
        print(f"Testing Home Assistant {version}", flush=True)
        try:
            subprocess.run(
                [uv, "venv", "--allow-existing", "--python", row["python"], str(env)],
                check=True,
            )
            dependencies = [f"pytest-homeassistant-custom-component=={row['plugin']}"]
            if constraint := row.get("constraint"):
                dependencies.append(constraint)
            subprocess.run(
                [uv, "pip", "install", "--python", str(python), *dependencies],
                check=True,
            )
            subprocess.run(
                [
                    str(python),
                    "-c",
                    "import importlib.metadata as m, sys; "
                    "assert m.version('homeassistant') == sys.argv[1]; "
                    "assert m.version('pytest-homeassistant-custom-component') == sys.argv[2]; "
                    "print(sys.version)",
                    version,
                    row["plugin"],
                ],
                check=True,
            )
            subprocess.run([str(python), "-m", "pytest", "-q"], cwd=ROOT, check=True)
        except subprocess.CalledProcessError:
            failed.append(version)
    if failed:
        print("Failed environments: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
