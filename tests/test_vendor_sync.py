"""Tests for vendor-sync, run against a throwaway git repository as the source."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    # vendor-sync has no .py suffix, so it needs an explicit loader.
    loader = importlib.machinery.SourceFileLoader("vendor_sync", str(ROOT / "vendor-sync"))
    spec = importlib.util.spec_from_loader("vendor_sync", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def vs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """vendor-sync pointed at a source repo with log.py tagged v1.0.0 and v1.1.0."""
    source = tmp_path / "source"
    (source / "includes").mkdir(parents=True)
    _git(source, "init", "-q")
    for tag, text in (("v1.0.0", "ONE = 1\n"), ("v1.1.0", "TWO = 2\n")):
        (source / "includes" / "log.py").write_text(text)
        _git(source, "add", "-A")
        _git(source, "commit", "-q", "-m", tag)
        _git(source, "tag", tag)
    module = _load()
    monkeypatch.setattr(module, "SOURCE", source)
    return module


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    target = tmp_path / "tool"
    (target / "pkg").mkdir(parents=True)
    (target / "PY_INCLUDES_VERSION").write_text("v1.0.0\n")
    (target / "pyproject.toml").write_text(
        '[tool.python-includes]\npackage = "pkg"\nmodules = ["log"]\n'
    )
    return target


def test_sync_writes_the_pinned_version_under_a_header(vs: ModuleType, tool: Path) -> None:
    assert vs.main([str(tool)]) == 0
    text = (tool / "pkg" / "log.py").read_text()
    assert text.startswith("# Vendored from python-includes v1.0.0 (includes/log.py).")
    assert text.endswith("ONE = 1\n")
    assert "TWO" not in text  # the working tree is at v1.1.0; the pin wins


def test_check_passes_after_sync_and_writes_nothing(vs: ModuleType, tool: Path) -> None:
    vs.main([str(tool)])
    before = (tool / "pkg" / "log.py").stat().st_mtime_ns
    assert vs.main(["--check", str(tool)]) == 0
    assert (tool / "pkg" / "log.py").stat().st_mtime_ns == before


def test_check_fails_on_a_hand_edit(
    vs: ModuleType, tool: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vs.main([str(tool)])
    dest = tool / "pkg" / "log.py"
    dest.write_text(dest.read_text() + "# local tweak\n")
    assert vs.main(["--check", str(tool)]) == 1
    assert "differs from python-includes v1.0.0" in capsys.readouterr().err
    assert dest.read_text().endswith("# local tweak\n")  # --check never repairs


def test_check_fails_when_the_file_is_missing(
    vs: ModuleType, tool: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert vs.main(["--check", str(tool)]) == 1
    assert "missing" in capsys.readouterr().err
    assert not (tool / "pkg" / "log.py").exists()


def test_check_fails_after_a_pin_bump_until_resynced(vs: ModuleType, tool: Path) -> None:
    vs.main([str(tool)])
    (tool / "PY_INCLUDES_VERSION").write_text("v1.1.0\n")
    assert vs.main(["--check", str(tool)]) == 1
    assert vs.main([str(tool)]) == 0
    assert (tool / "pkg" / "log.py").read_text().endswith("TWO = 2\n")
    assert vs.main(["--check", str(tool)]) == 0


@pytest.mark.parametrize(
    ("pin", "needle"),
    [
        ("v9.9.9\n", "cannot read refs/tags/v9.9.9"),
        ("main\n", "expected a tag"),
        ("v1.0.0; rm -rf /\n", "expected a tag"),
    ],
)
def test_bad_pin_is_exit_2(
    vs: ModuleType, tool: Path, capsys: pytest.CaptureFixture[str], pin: str, needle: str
) -> None:
    (tool / "PY_INCLUDES_VERSION").write_text(pin)
    assert vs.main([str(tool)]) == 2
    assert needle in capsys.readouterr().err


@pytest.mark.parametrize(
    "manifest",
    [
        "",
        '[tool.python-includes]\npackage = "pkg"\n',
        '[tool.python-includes]\npackage = "pkg"\nmodules = []\n',
        '[tool.python-includes]\npackage = "../escape"\nmodules = ["log"]\n',
        '[tool.python-includes]\npackage = "pkg"\nmodules = ["../../etc/passwd"]\n',
        '[tool.python-includes]\npackage = "absent"\nmodules = ["log"]\n',
        '[tool.python-includes]\npackage = "pkg"\nmodules = ["__init__"]\n',
        "not = [valid",
    ],
)
def test_bad_manifest_is_exit_2_and_writes_nothing(
    vs: ModuleType, tool: Path, manifest: str
) -> None:
    (tool / "pyproject.toml").write_text(manifest)
    assert vs.main([str(tool)]) == 2
    assert list((tool / "pkg").iterdir()) == []


def test_missing_pin_file_is_exit_2(vs: ModuleType, tool: Path) -> None:
    (tool / "PY_INCLUDES_VERSION").unlink()
    assert vs.main([str(tool)]) == 2


def test_a_module_the_tag_lacks_writes_nothing_at_all(vs: ModuleType, tool: Path) -> None:
    (tool / "pyproject.toml").write_text(
        '[tool.python-includes]\npackage = "pkg"\nmodules = ["log", "absent"]\n'
    )
    assert vs.main([str(tool)]) == 2
    assert list((tool / "pkg").iterdir()) == []


def test_undecodable_vendored_file_is_stale_not_a_crash(vs: ModuleType, tool: Path) -> None:
    (tool / "pkg" / "log.py").write_bytes(b"\xff\xfe not utf-8")
    assert vs.main(["--check", str(tool)]) == 1
    assert vs.main([str(tool)]) == 0
    assert vs.main(["--check", str(tool)]) == 0


def test_git_missing_is_exit_2(
    vs: ModuleType, tool: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    assert vs.main([str(tool)]) == 2
    assert "cannot run git" in capsys.readouterr().err


def test_carriage_returns_survive_byte_for_byte(vs: ModuleType, tool: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "includes" / "log.py").write_bytes(b"A = 1\r\nB = 2\r\n")
    _git(source, "-c", "core.autocrlf=false", "add", "-A")
    _git(source, "commit", "-q", "-m", "crlf")
    _git(source, "tag", "v1.2.0")
    (tool / "PY_INCLUDES_VERSION").write_text("v1.2.0\n")
    assert vs.main([str(tool)]) == 0
    assert (tool / "pkg" / "log.py").read_bytes().endswith(b"A = 1\r\nB = 2\r\n")
    assert vs.main(["--check", str(tool)]) == 0


def test_run_as_a_script_reports_drift_through_the_exit_status(tool: Path) -> None:
    # The real entry point against this repository's own history. Skipped until
    # the first tag exists.
    tags = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--list", "v*"], check=True, capture_output=True, text=True
    ).stdout.split()
    if not tags:
        pytest.skip("no release tag in this checkout")
    (tool / "PY_INCLUDES_VERSION").write_text(tags[0] + "\n")
    script = [str(ROOT / "vendor-sync")]
    assert subprocess.run([*script, "--check", str(tool)], check=False).returncode == 1
    assert subprocess.run([*script, str(tool)], check=False).returncode == 0
    assert subprocess.run([*script, "--check", str(tool)], check=False).returncode == 0
