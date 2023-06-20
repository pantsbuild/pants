# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Utils for scripts to interface with the outside world.

NB: We intentionally only use the standard library here, rather than using
Pants code and/or 3rd-party dependencies like `colors`, to ensure that all
scripts that import this file may still be invoked directly, rather than having
to run via `./pants run`.

We want to allow direct invocation of scripts for these reasons:
1) Consistency with how we invoke Bash scripts, which notably may _not_ be ran via `./pants run`.
2) More ergonomic command line arguments, e.g. `./src/python/pants_release/generate_github_workflows.py [args]`,
   rather than `./pants run src/python/pants_release:generate_github_workflows -- [args]`.
3) Avoid undesired dependencies on Pants for certain scripts.

Callers of this file, however, are free to dogfood Pants as they'd like, and any script
may be called via `./pants run` instead of direct invocation if desired.
"""
from __future__ import annotations

import time
from typing import NoReturn

_SCRIPT_START_TIME = time.time()

_COLOR_BLUE = "\x1b[34m"
_COLOR_RED = "\x1b[31m"
_COLOR_GREEN = "\x1b[32m"
_COLOR_RESET = "\x1b[0m"


def die(message: str) -> NoReturn:
    raise SystemExit(f"{_COLOR_RED}{message}{_COLOR_RESET}")


def green(message: str) -> None:
    print(f"{_COLOR_GREEN}{message}{_COLOR_RESET}")


def banner(message: str) -> None:
    minutes, seconds = elapsed_time()
    print(f"{_COLOR_BLUE}[=== {minutes:02d}:{seconds:02d} {message} ===]{_COLOR_RESET}")


def elapsed_time() -> tuple[int, int]:
    now = time.time()
    elapsed_seconds = int(now - _SCRIPT_START_TIME)
    return elapsed_seconds // 60, elapsed_seconds % 60
