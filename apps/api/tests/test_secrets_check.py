"""Unit tests for bundle secrets scanner (scripts/check-bundle-secrets.sh).

Proves that:
1. The production web bundle in apps/web/.next is completely free of server secrets.
2. The scanner actively catches and fails on synthetic canary secrets.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def test_production_bundle_is_clean_of_secrets():
    """Run check-bundle-secrets.sh against the actual built bundle in apps/web/.next."""
    root = _repo_root()
    bundle_dir = root / "apps/web" / ".next"
    script = root / "scripts" / "check-bundle-secrets.sh"

    assert script.exists(), f"Scanner script {script} not found"
    if not bundle_dir.exists():
        pytest.skip("apps/web/.next does not exist yet; skip until built")

    result = subprocess.run(
        [str(script), str(bundle_dir)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Secrets leak detected in bundle:\n{result.stderr}"
    assert "PASS: No secrets or server-only env var names found" in result.stdout


def test_scanner_catches_server_env_name_leak():
    """Canary test: scanner MUST exit 1 when server env var name is leaked."""
    root = _repo_root()
    script = root / "scripts" / "check-bundle-secrets.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        leak_file = Path(tmpdir) / "chunk-canary.js"
        leak_file.write_text(
            'const config = { groqKey: process.env.GROQ_API_KEY };',
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(script), tmpdir],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "LEAK DETECTED" in result.stderr
        assert "GROQ_API_KEY" in result.stderr


def test_scanner_catches_api_key_patterns():
    """Canary test: scanner MUST exit 1 when API key patterns appear."""
    root = _repo_root()
    script = root / "scripts" / "check-bundle-secrets.sh"

    # 1. Groq key canary
    with tempfile.TemporaryDirectory() as tmpdir:
        leak_file = Path(tmpdir) / "app.js"
        leak_file.write_text(
            'const key = "gsk_1234567890abcdef1234567890abcdef";',
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(script), tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "LEAK DETECTED" in result.stderr

    # 2. Google AI Studio key canary
    with tempfile.TemporaryDirectory() as tmpdir:
        leak_file = Path(tmpdir) / "app.js"
        leak_file.write_text(
            'const key = "AIzaSyD9876543210zyxwvutsrqponmlkjihg";',
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(script), tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "LEAK DETECTED" in result.stderr


def test_scanner_passes_on_clean_dummy_dir():
    """Scanner exits 0 when directory contains only clean client code."""
    root = _repo_root()
    script = root / "scripts" / "check-bundle-secrets.sh"

    with tempfile.TemporaryDirectory() as tmpdir:
        clean_file = Path(tmpdir) / "bundle.js"
        clean_file.write_text(
            'function add(a, b) { return a + b; } console.log("Hello tutor");',
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(script), tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout
