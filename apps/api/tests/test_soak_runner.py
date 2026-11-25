"""Unit tests for the soak test harness (scripts/soak.py)."""

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
soak_script_path = REPO_ROOT / "scripts" / "soak.py"
spec = importlib.util.spec_from_file_location("soak", soak_script_path)
assert spec and spec.loader
soak_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak_module)
SoakHarness = soak_module.SoakHarness


@pytest.mark.asyncio
async def test_soak_harness_short_run():
    """Verify soak harness completes a short cycle and generates valid reports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        harness = SoakHarness(
            duration_seconds=2.0,  # 2 second test run
            sample_interval=1.0,
            output_dir=out_dir,
        )

        report = await harness.run()

        assert report["metadata"]["status"] == "PASS"
        assert report["summary"]["turns_completed"] >= 1
        assert report["summary"]["turns_failed"] == 0
        assert "memory" in report
        assert "stages" in report

        # Verify output files
        json_file = out_dir / "soak_report.json"
        md_file = out_dir / "soak_report.md"

        assert json_file.exists()
        assert md_file.exists()

        with open(json_file, "r", encoding="utf-8") as f:
            saved_json = json.load(f)
            assert saved_json["summary"]["turns_completed"] >= 1

        md_text = md_file.read_text(encoding="utf-8")
        assert "# Soak Test Report" in md_text
        assert "Headline Results" in md_text
        assert "PASS" in md_text
