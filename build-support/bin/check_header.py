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

EXPECTED_NUM_PY2_LINES = 6
EXPECTED_NUM_PY3_LINES = 3

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
  lines = get_header_lines(filename)
  check_header_present(filename, lines)
  is_py3_file = all("from __future__" not in line for line in lines)
  if is_py3_file:
    lines = lines[:EXPECTED_NUM_PY3_LINES]
    copyright_line_index = 0
    expected_header = EXPECTED_HEADER_PY3
  else:
    copyright_line_index = 1
    expected_header = EXPECTED_HEADER_PY2
  check_copyright_year(
    filename, copyright_line=lines[copyright_line_index], is_newly_created=is_newly_created
  )
  check_matches_header(
    filename, lines, expected_header=expected_header, copyright_line_index=copyright_line_index
  )


def get_header_lines(filename: str) -> List[str]:
  try:
    with open(filename, 'r') as f:
      # We grab an extra line in case there is a shebang.
      lines = [f.readline() for _ in range(0, EXPECTED_NUM_PY2_LINES + 1)]
  except IOError as e:
    raise HeaderCheckFailure(f"{filename}: error while reading input ({e})")
  # If a shebang line is included, remove it. Otherwise, we will have conservatively grabbed
  # one extra line at the end for the shebang case that is no longer necessary.
  lines.pop(0 if lines[0].startswith("#!") else - 1)
  return lines


def check_header_present(filename: str, lines: List[str]) -> None:
  num_nonempty_lines = len([line for line in lines if line])
  if num_nonempty_lines < EXPECTED_NUM_PY3_LINES:
    raise HeaderCheckFailure(f"{filename}: missing the expected header")


def check_copyright_year(filename: str, *, copyright_line: str, is_newly_created: bool) -> None:
  """Check that copyright is current year if for a new file, else that it's within
  the current centuury."""
  year = copyright_line[12:16]
  if is_newly_created and year != _current_year:
    raise HeaderCheckFailure(f'{filename}: copyright year must be {_current_year} (was {year})')
  elif not _current_century_regex.match(year):
    raise HeaderCheckFailure(
      f"{filename}: copyright year must match '{_current_century_regex.pattern}' (was {year}): " +
      f"current year is {_current_year}"
    )


def check_matches_header(
  filename: str, lines: List[str], *, expected_header: str, copyright_line_index: int
) -> None:
  copyright_line = lines[copyright_line_index]
  sanitized_lines = lines.copy()
  sanitized_lines[copyright_line_index] = "# Copyright YYYY" + copyright_line[16:]
  if "".join(sanitized_lines) != expected_header:
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
