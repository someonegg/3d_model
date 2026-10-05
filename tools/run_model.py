"""Run model scripts with the shared tools and local source imports available."""

import runpy
import sys
from pathlib import Path


def main():
    script = Path(sys.argv[1]).resolve()
    repo = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(script.parent), str(repo), str(repo / "tools")]
    sys.argv = sys.argv[1:]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
