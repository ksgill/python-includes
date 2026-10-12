"""Tests for includes/log.py: verbosity tiers, colour gating, sanitizing, emit().

Pure stdlib, no mocking of anything external -- these tests exercise the
real print-to-stream code paths, using pytest's capsys to capture stdout and
stderr.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest

from includes import log


@pytest.fixture(autouse=True)
def _reset_verbosity() -> Iterator[None]:
    """log._verbosity is module-global state; isolate each test from it."""
    log.set_verbosity(log.WARN)
    yield
    log.set_verbosity(log.INFO)


_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


# --------------------------------------------------------------------------
# set_verbosity tiers
# --------------------------------------------------------------------------


def test_verbosity_0_shows_only_warn_and_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(0)
    log.debug("dbg-msg")
    log.info("info-msg")
    log.warn("warn-msg")
    log.error("error-msg")
    err = capsys.readouterr().err
    assert "dbg-msg" not in err
    assert "info-msg" not in err
    assert "warn-msg" in err
    assert "error-msg" in err


def test_verbosity_1_adds_info_not_debug(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(1)
    log.debug("dbg-msg")
    log.info("info-msg")
    err = capsys.readouterr().err
    assert "dbg-msg" not in err
    assert "info-msg" in err


def test_verbosity_2_adds_debug(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(2)
    log.debug("dbg-msg")
    log.info("info-msg")
    err = capsys.readouterr().err
    assert "dbg-msg" in err
    assert "info-msg" in err


def test_verbosity_above_2_still_shows_debug(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(5)
    log.debug("dbg-msg")
    assert "dbg-msg" in capsys.readouterr().err


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_warn_and_error_print_at_warn_and_above(
    verbosity: int, capsys: pytest.CaptureFixture[str]
) -> None:
    log.set_verbosity(verbosity)
    log.warn("always-warn")
    log.error("always-error")
    err = capsys.readouterr().err
    assert "always-warn" in err
    assert "always-error" in err


def test_success_gated_same_as_info(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(0)
    log.success("s-msg")
    assert "s-msg" not in capsys.readouterr().err
    log.set_verbosity(1)
    log.success("s-msg")
    assert "s-msg" in capsys.readouterr().err


def test_section_gated_same_as_info(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(0)
    log.section("Phase One")
    assert "Phase One" not in capsys.readouterr().err
    log.set_verbosity(1)
    log.section("Phase One")
    assert "Phase One" in capsys.readouterr().err


# --------------------------------------------------------------------------
# message content, formatting
# --------------------------------------------------------------------------


def test_log_lines_carry_a_timestamp_and_level_label(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(0)
    log.warn("hello")
    err = capsys.readouterr().err
    assert _TIMESTAMP_RE.match(err) is not None
    assert "[WARN]" in err
    assert "hello" in err


def test_error_label_and_info_label(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(1)
    log.error("boom")
    log.info("progress")
    log.debug("suppressed-at-tier-1")
    log.set_verbosity(2)
    log.debug("shown-at-tier-2")
    err = capsys.readouterr().err
    assert "[ERROR]" in err
    assert "boom" in err
    assert "[INFO]" in err
    assert "progress" in err
    assert "suppressed-at-tier-1" not in err
    assert "[DEBUG]" in err
    assert "shown-at-tier-2" in err


def test_message_passed_through_verbatim_no_alteration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(0)
    weird = "message with ?KISMET=abc123 and unicode ☃"
    log.warn(weird)
    assert weird in capsys.readouterr().err


# --------------------------------------------------------------------------
# emit(): the stdout data channel, undecorated
# --------------------------------------------------------------------------


def test_emit_writes_plain_text_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    log.emit("tool: sent 5 probe request(s)")
    captured = capsys.readouterr()
    assert captured.out == "tool: sent 5 probe request(s)\n"
    assert captured.err == ""


def test_emit_default_argument_prints_blank_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.emit()
    assert capsys.readouterr().out == "\n"


def test_emit_has_no_timestamp_or_level_label(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.emit("plain data line")
    out = capsys.readouterr().out
    assert out == "plain data line\n"
    assert "[" not in out  # no [INFO]/[WARN]-style decoration
    assert _TIMESTAMP_RE.match(out) is None


def test_emit_ignores_verbosity(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(0)
    log.emit("always shown")
    assert "always shown" in capsys.readouterr().out


# --------------------------------------------------------------------------
# die()
# --------------------------------------------------------------------------


def test_die_raises_system_exit_1_and_logs_as_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        log.die("fatal problem")
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "[ERROR]" in err
    assert "fatal problem" in err


# --------------------------------------------------------------------------
# colour gating
# --------------------------------------------------------------------------


class _Tty:
    def isatty(self) -> bool:
        return True


class _Pipe:
    def isatty(self) -> bool:
        return False


class TestColourDecision:
    def test_colour_on_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")
        assert log._colour(_Tty()) is True

    def test_no_colour_when_redirected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")
        assert log._colour(_Pipe()) is False

    def test_no_color_env_wins_even_on_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("", "1", "anything"):
            monkeypatch.setenv("NO_COLOR", value)
            assert log._colour(_Tty()) is False

    def test_dumb_terminal_gets_no_colour(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "dumb")
        assert log._colour(_Tty()) is False

    def test_no_term_set_and_not_a_tty_is_no_colour(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        assert log._colour(_Pipe()) is False


class _RecordingTty:
    """A fake stream that reports isatty() True and records writes."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


def test_end_to_end_colour_escape_codes_appear_on_a_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    fake = _RecordingTty()
    monkeypatch.setattr(log.sys, "stderr", fake)
    log.set_verbosity(0)
    log.warn("coloured line")
    text = "".join(fake.written)
    assert "\033[0;33m" in text  # _YEL
    assert "\033[0m" in text  # _RST
    assert "coloured line" in text


def test_end_to_end_no_escape_codes_when_no_color_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    fake = _RecordingTty()
    monkeypatch.setattr(log.sys, "stderr", fake)
    log.set_verbosity(0)
    log.warn("plain line")
    text = "".join(fake.written)
    assert "\033[" not in text
    assert "plain line" in text


# --------------------------------------------------------------------------
# control-character sanitization (defence-in-depth: a field from outside the
# tool must not inject terminal escapes or spoof log lines)
# --------------------------------------------------------------------------


def test_ansi_escape_in_message_is_rendered_inert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(0)
    # An embedded colour escape plus a CR/LF spoof of a fake log line.
    log.warn("hostile \x1b[31mRED\x1b[0m field\r\n[ERROR] spoofed")
    err = capsys.readouterr().err
    # capsys stderr is not a tty, so the tool adds no colour of its own -- any
    # ESC byte here would have come from the message. None survive.
    assert "\x1b" not in err
    # The control bytes (ESC/CR/LF) are stripped; the visible text remains.
    assert "hostile [31mRED[0m field[ERROR] spoofed" in err
    # No embedded newline could start a new logical line inside the message.
    assert err.count("\n") == 1  # only print()'s trailing newline


def test_c1_control_bytes_are_stripped(capsys: pytest.CaptureFixture[str]) -> None:
    log.warn("a\x9bb\x85c")  # C1 CSI (0x9b) and NEL (0x85)
    err = capsys.readouterr().err
    assert "\x9b" not in err
    assert "\x85" not in err
    assert "abc" in err


def test_tab_is_preserved_in_messages(capsys: pytest.CaptureFixture[str]) -> None:
    log.warn("col1\tcol2")
    assert "col1\tcol2" in capsys.readouterr().err


def test_emit_is_not_sanitized_byte_exact_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # emit() is the stdout data channel and must stay byte-exact, not sanitized.
    log.emit("tab\tand\x1bescape")
    assert capsys.readouterr().out == "tab\tand\x1bescape\n"


def test_own_colour_codes_survive_message_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The colour prefix is added AFTER the message is sanitized, so a coloured
    # line still carries the tool's real escape codes.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    fake = _RecordingTty()
    monkeypatch.setattr(log.sys, "stderr", fake)
    log.set_verbosity(0)
    log.warn("clean message")
    text = "".join(fake.written)
    assert "\033[0;33m" in text  # _YEL prefix intact
    assert "\033[0m" in text  # _RST intact
    assert "clean message" in text


# --------------------------------------------------------------------------
# defaults and the ERROR tier
# --------------------------------------------------------------------------


def test_default_verbosity_is_info() -> None:
    import importlib

    fresh = importlib.reload(log)
    assert fresh._verbosity == fresh.INFO


def test_error_tier_suppresses_warnings_but_not_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log.set_verbosity(log.ERROR)
    log.warn("warn-msg")
    log.error("error-msg")
    err = capsys.readouterr().err
    assert "warn-msg" not in err
    assert "error-msg" in err


def test_die_prints_even_at_the_error_tier(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(log.ERROR)
    with pytest.raises(SystemExit):
        log.die("fatal")
    assert "fatal" in capsys.readouterr().err


def test_section_title_is_sanitized(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_verbosity(log.INFO)
    log.section("a\x1b[31mb\nc")
    err = capsys.readouterr().err
    assert "\x1b" not in err
    # Blank line, rule, title, rule: the embedded newline added no fifth line.
    assert err.splitlines() == ["", "=" * 68, "  a[31mbc", "=" * 68]


@pytest.mark.parametrize(
    "char",
    ["\x7f", "\u2028", "\u2029", "\u202a", "\u202e", "\u2066", "\u2069"],
)
def test_del_line_separators_and_bidi_controls_are_stripped(
    capsys: pytest.CaptureFixture[str], char: str
) -> None:
    log.warn(f"left{char}right")
    assert "leftright" in capsys.readouterr().err


def test_ordinary_non_ascii_text_survives(capsys: pytest.CaptureFixture[str]) -> None:
    log.warn("café \u05e9\u05dc\u05d5\u05dd \u2603")
    assert "café \u05e9\u05dc\u05d5\u05dd \u2603" in capsys.readouterr().err
