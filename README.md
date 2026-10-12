# python-includes

Canonical modules for self-contained Python command-line tools, and the CI
workflow those tools share. The Python counterpart of
[bash-includes](https://github.com/ksgill/bash-includes).

Python 3.11+, standard library only.

## What is here

| | |
|---|---|
| `includes/log.py` | Logging and reporting: timestamped status to stderr, colour gated on tty / `NO_COLOR` / `TERM=dumb`, four verbosity tiers, control characters stripped from every status message, `emit()` for undecorated stdout. |
| `vendor-sync` | Copies pinned modules into a tool, or checks that the copies are current. |
| `.github/workflows/python-ci.yml` | Reusable workflow: `ruff check`, `ruff format --check`, `mypy` (strict), `pytest` on a version matrix, a vendored-file drift check, and a bare-checkout smoke test. |
| `pyproject.toml` | This repository's configuration, and the template for a consumer's. |

## Why modules are vendored, not installed

The tools that use this run straight from a checkout with nothing installed on
the target. A pip dependency would break that, and a build step producing a
single file would add a second runnable form to test. So each tool carries a
real, readable copy of the module in its own package, pinned to a tag here, and
CI fails if the copy drifts.

The cost is one commit per tool when a module changes.

## Using it in a tool

Pin a tag and say what to copy where:

```bash
echo v1.0.0 > PY_INCLUDES_VERSION
```

```toml
# pyproject.toml
[tool.python-includes]
package = "my_tool"       # the package directory to copy into
modules = ["log"]         # includes/<name>.py for each
```

Then, from a checkout of this repository:

```bash
path/to/python-includes/vendor-sync path/to/my-tool            # write
path/to/python-includes/vendor-sync --check path/to/my-tool
```

`vendor-sync` reads each module from the pinned tag in git history, not from
the working tree, so this checkout does not need to be at that tag — only to
have it (`git fetch --tags`). The copy is written to `<package>/<name>.py`
under a two-line header naming the tag. Exit codes: `0` current or written,
`1` (`--check` only) a copy is stale, missing, or was edited, `2` the pin or
the manifest is wrong.

A vendored file is never edited in place. Change it here, tag a release, bump
`PY_INCLUDES_VERSION` in the tool, run `vendor-sync`, commit both.

## CI for a tool

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  python:
    uses: ksgill/python-includes/.github/workflows/python-ci.yml@main
    with:
      smoke: |
        ./my-tool --help
        python3 -m my_tool --help
```

`smoke` runs from a bare checkout with nothing installed; leave it empty and
the job is skipped. `python-versions` (default `["3.11", "3.14"]`) is the test
matrix: the floor and the newest version deployed.

The workflow assumes the tool:

- carries the `[tool.ruff]`, `[tool.mypy]` and `[tool.pytest.ini_options]`
  tables from the template, so every command runs with no arguments. Two
  values in the template are this repository's own and must be changed:
  `[tool.setuptools.packages.find] include` and `[tool.mypy] files`;
- vendors from here. The `vendor` job fails without a `PY_INCLUDES_VERSION`
  file; `vendor: false` turns it off for a repository that vendors nothing;
- has no runtime dependencies. The lint job installs only `ruff` and `mypy`.

Tools call the workflow at `@main`, so a change pushed here takes effect in
every tool's CI at once. That is the point — one definition — and the cost: a
mistake here breaks all of them together. The vendored modules are pinned by
tag and do not move that way.

The lint, type-check and test tools are pinned in `dev-requirements.txt`, the
one place their versions are written. The workflow installs from it; build a
development venv from it too, or a finding in one place will not reproduce in
the other.

## Using `log`

```python
from . import log

log.set_verbosity(log.DEBUG if args.verbose else log.INFO)
log.info("starting")  # stderr, timestamped
log.warn("that looks wrong")
log.emit(result)  # stdout, undecorated: the data channel
log.die("cannot continue: fix X and re-run")  # error, then exit 1
```

`log.use_colour(stream)` is the test the status lines use — no colour under
`NO_COLOR` or `TERM=dumb`, or off a terminal — for a tool that colours its own
report on stdout.

Tiers are `ERROR` (-1), `WARN` (0), `INFO` (1, the default) and `DEBUG` (2). A
tool that is quiet unless given `-v` can pass the flag count straight to
`set_verbosity`.

Status messages have control characters stripped, so text from outside the
tool cannot inject terminal escapes or forge a log line. `emit()` is exempt: it
is byte-exact. Redacting secrets is the caller's job.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r dev-requirements.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy && .venv/bin/pytest
```
