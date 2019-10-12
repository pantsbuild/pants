#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import subprocess

from common import die


def main() -> None:
  globs = create_parser().parse_args().globs
  try:
    subprocess.run([
      "./pants",
      "--tag=type_checked",
      "--backend-packages=pants.contrib.mypy",
      "lint",
      "--lint-mypy-verbose",
      "--lint-mypy-whitelist-tag-name=type_checked",
      "--lint-mypy-config-file=build-support/mypy/mypy.ini",
      *globs,
    ], check=True)
  except subprocess.CalledProcessError:
    die("Please fix the above errors and run again.")


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "globs",
    nargs='*',
    default=["build-support::", "contrib::", "src/python::", "tests/python::", "pants-plugins::"]
  )
  return parser


if __name__ == '__main__':
  main()
