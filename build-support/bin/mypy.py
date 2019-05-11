#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import subprocess
from typing import List

from common import die


def main():
  targets = create_parser().parse_args().targets
  run_mypy(targets)


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Run MyPy with our config file.")
  parser.add_argument(
    "targets",
    default=["build-support::", "src/python::", "tests/python::", "contrib::"],
    nargs="*",
    help="Pants targets, e.g. `tests::`.",
  )
  return parser


def run_mypy(targets: List[str]) -> None:
  command = [
    "./pants",
    "mypy",
    "--mypy-mypy-version=0.701",
    "--config-file=build-support/mypy/mypy.ini",
  ]
  try:
    subprocess.run(command + targets, check=True)
  except subprocess.CalledProcessError:
    die("Please fix the above type errors and run again.")


if __name__ == "__main__":
  main()
