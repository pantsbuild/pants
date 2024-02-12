# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

VERSION_PATH = Path(__file__).parent.parent.parent.parent / "pants" / "_version" / "VERSION"
CONTRIBUTORS_PATH = Path("CONTRIBUTORS.md")

_SCRIPT_START_TIME = time.time()

_COLOR_BLUE = "\x1b[34m"
_COLOR_RED = "\x1b[31m"
_COLOR_GREEN = "\x1b[32m"
_COLOR_RESET = "\x1b[0m"


def die(message: str) -> NoReturn:
    raise SystemExit(f"{_COLOR_RED}{message}{_COLOR_RESET}")


def green(message: str) -> None:
    print(f"{_COLOR_GREEN}{message}{_COLOR_RESET}", file=sys.stderr)


def banner(message: str) -> None:
    minutes, seconds = elapsed_time()
    print(
        f"{_COLOR_BLUE}[=== {minutes:02d}:{seconds:02d} {message} ===]{_COLOR_RESET}",
        file=sys.stderr,
    )


def elapsed_time() -> tuple[int, int]:
    now = time.time()
    elapsed_seconds = int(now - _SCRIPT_START_TIME)
    return elapsed_seconds // 60, elapsed_seconds % 60


def sorted_contributors(git_range: str) -> list[str]:
    contributors = set(
        subprocess.run(
            ["git", "log", "--use-mailmap", "--format=format:%aN", git_range],
            stdout=subprocess.PIPE,
            check=True,
        )
        .stdout.decode()
        .splitlines()
    )
    contributors -= {"dependabot[bot]", "Worker Pants (Pantsbuild GitHub Automation Bot)"}
    return sorted(contributors)
