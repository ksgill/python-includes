"""Logging and reporting for self-contained command-line tools.

Mirrors the semantics of bash-includes' log.sh, so a Python tool's output reads
the same as the shell tools it sits beside: timestamped status lines to stderr,
colour only when the stream is a tty, NO_COLOR and TERM=dumb honoured.

Anything whose output *is* the answer goes to stdout via `emit()` with no
decoration, so it stays greppable and pipeable. Everything else is progress and
goes to stderr.

Verbosity is one integer, set once with `set_verbosity()`:

    ERROR (-1)  errors only
    WARN  (0)   + warnings
    INFO  (1)   + info, success and section headings  (the default)
    DEBUG (2)   + debug

A tool with a repeatable `-v` flag that should be quiet by default can pass the
count straight in: 0, 1, 2.

Every status message has control characters stripped before it is printed (see
`_sanitize`). Redacting secrets is the caller's job: this module prints what it
is given.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import NoReturn, TextIO

_RED = "\033[0;31m"
_GRN = "\033[0;32m"
_YEL = "\033[0;33m"
_MAG = "\033[0;35m"
_CYN = "\033[0;36m"
_RST = "\033[0m"

ERROR = -1
WARN = 0
INFO = 1
DEBUG = 2

_verbosity = INFO

# Strip C0 control bytes (0x00-0x1F) except tab, DEL, the C1 controls (0x80-0x9F)
# and the Unicode line-breaking and bidirectional-control characters
# from every status *message* before printing. Messages are routinely built from
# input the tool does not control -- a field from a network service, an SSID off
# the air, a filename. Without this, an embedded ESC could inject terminal escape
# sequences, and a newline could spoof a log line on the operator's terminal. The
# tool's own colour codes are added
# AFTER sanitization (they wrap the sanitized message), so they are unaffected.
# emit() is intentionally exempt -- it is the byte-exact stdout data channel.
_CONTROL_STRIP = {c: None for c in range(0x20) if c != 0x09}
_CONTROL_STRIP.update(dict.fromkeys(range(0x7F, 0xA0)))  # DEL and the C1 controls
# Not control bytes, but they do the same damage on a terminal that honours
# them: the line and paragraph separators break a line, and the bidirectional
# embeddings, overrides and isolates reorder the text that follows.
_CONTROL_STRIP.update(dict.fromkeys((0x2028, 0x2029)))
_CONTROL_STRIP.update(dict.fromkeys(range(0x202A, 0x202F)))
_CONTROL_STRIP.update(dict.fromkeys(range(0x2066, 0x206A)))


def _sanitize(message: str) -> str:
    return message.translate(_CONTROL_STRIP)


def set_verbosity(level: int) -> None:
    """Set the stderr verbosity: ERROR, WARN, INFO or DEBUG (or a -v count)."""
    global _verbosity
    _verbosity = level


def use_colour(stream: TextIO) -> bool:
    """Whether escape sequences are safe to write to *stream*.

    Public so a tool that colours its own stdout report makes the same decision
    as the status lines do: no colour under NO_COLOR or TERM=dumb, or when the
    stream is not a terminal.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    # TERM=dumb means the terminal cannot render escape sequences, so a tty
    # check alone is not enough -- `TERM=dumb` is how you ask a program to stop
    # colourising without unsetting NO_COLOR semantics elsewhere.
    if os.environ.get("TERM", "") == "dumb":
        return False
    return stream.isatty()


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(colour: str, label: str, stream: TextIO, message: str, min_level: int) -> None:
    if stream is sys.stderr and _verbosity < min_level:
        return
    prefix = f"{colour}[{label}]{_RST}" if use_colour(stream) else f"[{label}]"
    print(f"{_stamp()} {prefix} {_sanitize(message)}", file=stream, flush=True)


def info(message: str) -> None:
    _log(_CYN, "INFO", sys.stderr, message, INFO)


def success(message: str) -> None:
    _log(_GRN, "SUCCESS", sys.stderr, message, INFO)


def debug(message: str) -> None:
    _log(_MAG, "DEBUG", sys.stderr, message, DEBUG)


def warn(message: str) -> None:
    _log(_YEL, "WARN", sys.stderr, message, WARN)


def error(message: str) -> None:
    _log(_RED, "ERROR", sys.stderr, message, ERROR)


def section(title: str) -> None:
    if _verbosity < INFO:
        return
    safe = _sanitize(title)
    print(f"\n{'=' * 68}\n  {safe}\n{'=' * 68}", file=sys.stderr, flush=True)


def die(message: str) -> NoReturn:
    """Fatal error. The message should say what to do next, not just what broke."""
    error(message)
    raise SystemExit(1)


def emit(text: str = "") -> None:
    """Report output. Plain stdout, no decoration -- this is the data channel."""
    print(text, file=sys.stdout)
