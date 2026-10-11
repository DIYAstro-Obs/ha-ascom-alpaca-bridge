import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ha_stubs  # noqa: E402,F401  (installs the Home Assistant stand-ins)
