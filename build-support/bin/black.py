#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import subprocess
import sys

from common import git_merge_base


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Formats all python files since master with black through pants.",
  )
  parser.add_argument("-f", "--fix", action="store_true",
    help="Instead of erroring on files with incorrect formatting, fix those files."
  )
  return parser


def main() -> None:
  args= create_parser().parse_args()
  merge_base = git_merge_base()
  goal = "fmt-v2" if args.fix else "lint-v2"
  command = ["./pants", f"--changed-parent={merge_base}", goal]
  process = subprocess.run(command)
  sys.exit(process.returncode)

if __name__ == "__main__":
  main()
