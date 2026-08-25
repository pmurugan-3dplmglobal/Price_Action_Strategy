# validation/run_datta_validation.py
"""Driver script to validate the price‑action engine against the 27 Datta ground‑truth charts.

The script walks through the image directory, extracts the expected anchor/target data
using :pyfunc:`ground_truth_extractor.extract_annotations`, runs the engine's pattern
detectors on the corresponding historical candle data (via ``common.trading_core``
helpers), and compares the engine output with the ground‑truth.
A summary markdown report is written to ``scratch/native_scan_verification.md``.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Ensure the validation package is importable when running this script directly
sys.path.append(str(Path(__file__).parent.parent))

from validation.ground_truth_extractor import extract_annotations

# Import the engine's detection utilities – we use the generic breakout scanner.
# The engine expects a DataFrame of candles; for this proof‑of‑concept we will
# simply record that the comparison took place. In a full implementation you would
# fetch the historic candles (e.g. via ``common.trading_core.fetch_and_resample_candles``)
# and pass them to ``common.trading_core.scan_anchor_bcd_breakout_generic``.

def _dummy_engine_scan(_image_path: str) -> Dict[str, Any]:
    """Placeholder for the real engine scan.

    Returns a dictionary with the same keys as ``extract_annotations`` so the
    comparison logic can be demonstrated without network calls.
    """
    # In a real run you would load candle data and invoke the engine.
    return {
        "anchor_a": {"time": "2026-01-01 09:15", "price": 100.0},
        "anchor_b": {"time": "2026-01-01 09:30", "price": 102.0},
        "anchor_c": {"time": "2026-01-01 09:45", "price": 101.5},
        "anchor_d": {"time": "2026-01-01 10:00", "price": 103.0},
        "targets": {"sl": 99.0, "t1": 105.0, "t2": 110.0, "t3": 115.0},
    }

def compare_ground_truth(gt: Dict[str, Any], engine: Dict[str, Any]) -> Dict[str, Any]:
    """Simple field‑wise equality comparison.

    Returns a dictionary summarising matches/mismatches for each key.
    """
    result = {}
    for key in ["anchor_a", "anchor_b", "anchor_c", "anchor_d", "targets"]:
        result[key] = gt.get(key) == engine.get(key)
    return result

def run_validation(image_dir: str) -> List[Dict[str, Any]]:
    """Run validation on all chart images in *image_dir*.

    Returns a list of result dictionaries, each containing the image name,
    ground‑truth data, dummy engine output, and a comparison summary.
    """
    results = []
    for entry in os.scandir(image_dir):
        if not entry.is_file() or not entry.name.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        gt = extract_annotations(entry.path)
        engine_out = _dummy_engine_scan(entry.path)
        cmp = compare_ground_truth(gt, engine_out)
        results.append({
            "image": entry.name,
            "ground_truth": gt,
            "engine": engine_out,
            "match": cmp,
        })
    return results

if __name__ == "__main__":
    IMG_DIR = r"G:\Poovendan\AI\Trading\Share\RefDoc\Chart\Datta\New"
    from validation.report_generator import generate_report
    validation_results = run_validation(IMG_DIR)
    report_path = Path(__file__).parents[1] / "scratch" / "native_scan_verification.md"
    generate_report(validation_results, report_path)
    print(f"Verification report written to {report_path}")
