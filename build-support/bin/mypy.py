#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess


def main() -> None:
  subprocess.run([
    "./pants",
    "--backend-packages=pants.contrib.mypy",
    "lint",
    "--lint-mypy-verbose",
    "--lint-mypy-whitelist-tag-name=type_checked",
    "--lint-mypy-config-file=build-support/mypy/mypy.ini",
    "build-support::",
    "src/python::",
    "tests/python::",
    "pants-plugins::",
  ], check=True)


if __name__ == '__main__':
  main()
