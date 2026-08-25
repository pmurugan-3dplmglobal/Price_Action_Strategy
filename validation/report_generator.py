# validation/report_generator.py
"""Generate a markdown report summarising the Datta chart validation.

The function receives the list returned by :pyfunc:`run_datta_validation.run_validation`
and writes a human‑readable summary to *report_path*.
"""

from pathlib import Path
from typing import List, Dict, Any

def _format_match_summary(match: Dict[str, Any]) -> str:
    """Convert the boolean match dict into a concise markdown line.
    """
    parts = []
    for key, ok in match.items():
        emoji = "✅" if ok else "❌"
        parts.append(f"{emoji} {key}")
    return ", ".join(parts)

def generate_report(results: List[Dict[str, Any]], report_path: Path) -> None:
    """Write *results* to *report_path* as a markdown document.
    """
    lines = ["# Datta Chart Ground‑Truth Validation Report", ""]
    total = len(results)
    matches = 0
    for r in results:
        lines.append(f"## {r['image']}")
        lines.append("")
        lines.append("**Ground‑Truth**")
        lines.append("```json")
        import json
        lines.append(json.dumps(r["ground_truth"], indent=2))
        lines.append("```")
        lines.append("")
        lines.append("**Engine Output (placeholder)**")
        lines.append("```json")
        lines.append(json.dumps(r["engine"], indent=2))
        lines.append("```")
        lines.append("")
        lines.append("**Field‑wise Comparison**")
        lines.append(_format_match_summary(r["match"]))
        lines.append("---")
        lines.append("")
        if all(r["match"].values()):
            matches += 1
    # Summary
    lines.insert(2, f"*Processed {total} charts – {matches}/{total} fully matched.*")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
