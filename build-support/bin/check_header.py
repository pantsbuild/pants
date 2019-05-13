#!/usr/bin/env python3
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import datetime
import os
import re
from textwrap import dedent
from typing import Iterable, List

from common import die


EXPECTED_HEADER_PY2 = dedent("""\
  # coding=utf-8
  # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
  # Licensed under the Apache License, Version 2.0 (see LICENSE).

  from __future__ import absolute_import, division, print_function, unicode_literals

  """)

EXPECTED_HEADER_PY3 = dedent("""\
  # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
  # Licensed under the Apache License, Version 2.0 (see LICENSE).

  """)


_current_year = str(datetime.datetime.now().year)
_current_century_regex = re.compile(r'20\d\d')


class HeaderCheckFailure(Exception):
  """This is only used for control flow and to propagate the `.message` field."""


def main() -> None:
  args = create_parser().parse_args()
  header_parse_failures = []
  for directory in args.dirs:
    header_parse_failures.extend(check_dir(directory, args.files_added))
  if header_parse_failures:
    failures = '\n  '.join(str(failure) for failure in header_parse_failures)
    die(f"""\
ERROR: All .py files other than __init__.py should start with the header:
{EXPECTED_HEADER_PY3}

If they must support Python 2 still, they should start with the header:
{EXPECTED_HEADER_PY2}

---

The following {len(header_parse_failures)} file(s) do not conform:
{failures}""")


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Check that all .py files start with the appropriate header."
  )
  parser.add_argument("dirs", nargs="+",
    help="The directories to check. Will recursively check subdirectories."
  )
  parser.add_argument("-a", "--files-added", nargs="*", default=[],
    help="Any passed files will be checked for a current copyright year."
  )
  return parser


def check_header(filename: str, *, is_newly_created: bool = False) -> None:
  """Raises `HeaderCheckFailure` if the header doesn't match."""
  expected_num_py2_lines = 6
  expected_num_py3_lines = 3
  try:
    with open(filename, 'r') as f:
      # We grab an extra line in case there is a shebang.
      first_lines = [f.readline() for _ in range(0, expected_num_py2_lines + 1)]
  except IOError as e:
    raise HeaderCheckFailure(f"{filename}: error while reading input ({e})")
  # If a shebang line is included, remove it. Otherwise, we will have conservatively grabbed
  # one extra line at the end for the shebang case that is no longer necessary.
  first_lines.pop(0 if first_lines[0].startswith("#!") else - 1)
  # Check that the first lines even exists. Note that first_lines will always have an entry
  # for each line, even if the file is completely empty.
  if len([line for line in first_lines if line]) < expected_num_py3_lines:
    raise HeaderCheckFailure(f"{filename}: missing the expected header")
  is_py3_file = all("from __future__" not in line for line in first_lines)
  if is_py3_file:
    first_lines = first_lines[:expected_num_py3_lines]
  # Check copyright year. If it's a new file, it should be the current year. Else, it should
  # be within the current century.
  copyright_line_index = 0 if is_py3_file else 1
  copyright_line = first_lines[copyright_line_index]
  year = copyright_line[12:16]
  if is_newly_created and year != _current_year:
    raise HeaderCheckFailure(f'{filename}: copyright year must be {_current_year} (was {year})')
  elif not _current_century_regex.match(year):
    raise HeaderCheckFailure(
      f"{filename}: copyright year must match '{_current_century_regex.pattern}' (was {year}): " +
      f"current year is {_current_year}"
    )
  # Replace copyright_line with sanitized year.
  first_lines[copyright_line_index] = "# Copyright YYYY" + copyright_line[16:]
  if "".join(first_lines) not in (EXPECTED_HEADER_PY2, EXPECTED_HEADER_PY3):
    raise HeaderCheckFailure(f"{filename}: header does not match the expected header")


def check_dir(directory: str, newly_created_files: Iterable[str]) -> List[HeaderCheckFailure]:
  header_parse_failures: List[HeaderCheckFailure] = []
  for root, dirs, files in os.walk(directory):
    for f in files:
      if not f.endswith('.py') or os.path.basename(f) == '__init__.py':
        continue
      filename = os.path.join(root, f)
      try:
        check_header(filename, is_newly_created=filename in newly_created_files)
      except HeaderCheckFailure as e:
        header_parse_failures.append(e)
  return header_parse_failures


if __name__ == '__main__':
  main()
