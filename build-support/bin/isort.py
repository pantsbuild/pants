#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import re
import subprocess
from typing import List, Iterable

from common import die


def main() -> None:
  args = create_parser().parse_args()
  result = run_isort(fix=args.fix)
  parse_result(result)


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Run isort over build-support to ensure valid import order.")
  parser.add_argument(
    "-f", "--fix",
    action="store_true",
    help="Instead of erroring on bad import sort orders, fix those files."
  )
  return parser


def run_isort(*, fix: bool) -> subprocess.CompletedProcess:
  command = ["./pants", "--changed-parent=master", "fmt.isort"]
  if not fix:
    command.extend(["--", "--check-only"])
  return subprocess.run(command, encoding="utf-8", stdout=subprocess.PIPE)


def parse_result(result: subprocess.CompletedProcess) -> None:
  stdout = result.stdout.strip()
  if result.returncode == 0:
    if "Fixing" in stdout:
      fixed_files = '\n'.join(parse_fixed_files(stdout.split("\n")))
      print(f"The following files' imports were fixed:\n\n{fixed_files}")
  else:
    if "ERROR" in stdout:
      failing_targets = '\n'.join(parse_failing_files(stdout.split("\n")))
      die("The following files have incorrect import orders. Fix by running "
          f"`./build-support/isort.py --fix`.\n\n{failing_targets}")
    else:
      # NB: we intentionally don't swallow stderr, so that will be printed before
      # this message.
      die("Unexepcted failure.")


def parse_fixed_files(stdout: Iterable[str]) -> List[str]:
  fixed_lines = (line for line in stdout if "Fixing" in line)
  return _parse_file_names(fixed_lines)


def parse_failing_files(stdout: Iterable[str]) -> List[str]:
  error_lines = (line for line in stdout if "ERROR" in line)
  return _parse_file_names(error_lines, postfix=r'(?=\sImports)')


def _parse_file_names(
  lines: Iterable[str], *, prefix: str = r"(?<=pants/)", postfix: str = ""
  ) -> List[str]:
  return sorted(re.search(f"{prefix}.*{postfix}", line)[0] for line in lines)


if __name__ == "__main__":
  main()
