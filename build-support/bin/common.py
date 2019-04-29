# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Utils for scripts to interface with the outside world.

NB: We intentionally only use the standard library here, rather than using
Pants code and/or 3rd-party dependencies like `colors`, to ensure that all
scripts that import this file may still be invoked directly, rather than having
to run via `./pants run`.

We want to allow direct invocation of scripts for these reasons:
1) Consistency with how we invoke Bash scripts, which notably may _not_ be ran via `./pants run`.
2) More ergonomic command line arguments, e.g. `./build-support/bin/check_header.py src tests`,
   rather than `./pants run build-support/bin:check_header -- src tests`.
3) Avoid undesired dependencies on Pants for certain scripts. For example, `shellcheck.py`
   lints the `./pants` script, and we would like the script to still work even if `./pants`
   breaks. If we had to rely on invoking via `./pants run`, this would not be possible.

Callers of this file, however, are free to dogfood Pants as they'd like, and any script
may be called via `./pants run` instead of direct invocation if desired."""

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Tuple


_SCRIPT_START_TIME = time.time()

_CLEAR_LINE = "\x1b[K"
_COLOR_BLUE = "\x1b[34m"
_COLOR_RED = "\x1b[31m"
_COLOR_GREEN = "\x1b[32m"
_COLOR_RESET = "\x1b[0m"


def die(message: str) -> None:
  raise SystemExit(f"{_COLOR_RED}{message}{_COLOR_RESET}")


def green(message: str) -> None:
  print(f"{_COLOR_GREEN}{message}{_COLOR_RESET}")


def banner(message: str) -> None:
  minutes, seconds = elapsed_time()
  print(f"{_COLOR_BLUE}[=== {minutes:02d}:{seconds:02d} {message} ===]{_COLOR_RESET}")


def elapsed_time() -> Tuple[int, int]:
  now = time.time()
  elapsed_seconds = int(now - _SCRIPT_START_TIME)
  return elapsed_seconds // 60, elapsed_seconds % 60


@contextmanager
def travis_section(slug: str, message: str) -> Iterator[None]:
  travis_fold_state = "/tmp/.travis_fold_current"

  def travis_fold(action: str, target: str) -> None:
    print(f"travis_fold:{action}:{target}\r{_CLEAR_LINE}", end="")

  def read_travis_fold_state() -> str:
    with open(travis_fold_state, "r") as f:
      return f.readline()

  def write_slug_to_travis_fold_state() -> None:
    with open(travis_fold_state, "w") as f:
      f.write(slug)

  def remove_travis_fold_state() -> None:
    Path(travis_fold_state).unlink()

  travis_fold("start", slug)
  write_slug_to_travis_fold_state()
  banner(message)
  try:
    yield
  finally:
    travis_fold("end", read_travis_fold_state())
    remove_travis_fold_state()
