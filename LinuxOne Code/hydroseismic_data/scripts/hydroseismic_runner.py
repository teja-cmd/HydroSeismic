#!/usr/bin/env python3
"""HydroSeismic standalone pipeline entry point."""
from pathlib import Path
import runpy
import sys

BASE = Path("/home/ibm-user/hydroseismic_data")
PIPELINE = BASE / "scripts" / "hydroseismic_pipeline.py"

if not PIPELINE.is_file():
    print("Pipeline implementation is missing:", PIPELINE)
    print("Save the combined refresh-and-health-check code as hydroseismic_pipeline.py.")
    raise SystemExit(2)

runpy.run_path(str(PIPELINE), run_name="__main__")
