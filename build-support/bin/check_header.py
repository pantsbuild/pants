#!/usr/bin/env python3
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Helper for check_headers.sh to check .py files in the repo to see if they start with the
# appropriate headers.
#
# usage: check_header.py dir1 [ dir2 [ ... ] ]


import datetime
import os
import re
import sys
from textwrap import dedent
from typing import Iterable, List

EXPECTED_HEADER = dedent("""\
  # coding=utf-8
  # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
  # Licensed under the Apache License, Version 2.0 (see LICENSE).

  from __future__ import absolute_import, division, print_function, unicode_literals

  """)


_current_year = str(datetime.datetime.now().year)
_current_century_regex = re.compile(r'20\d\d')


class HeaderCheckFailure(Exception):
  """This is only used for control flow and to propagate the `.message` field."""


def check_header(filename: str, *, is_newly_created: bool = False) -> None:
  """Raises `HeaderCheckFailure` if the header doesn't match."""
  try:
    with open(filename, 'r') as f:
      first_lines = [f.readline() for _ in range(0, 7)]
  except IOError as e:
    raise HeaderCheckFailure(f"{filename}: error while reading input ({e})")
  # If a shebang line is included, remove it. Otherwise, we will have conservatively grabbed
  # one extra line at the end for the shebang case that is no longer necessary because.
  first_lines.pop(0 if first_lines[0].startswith("#!") else - 1)
  # Check copyright year. If a new file, it should be the current year. Else, it should be parsed
  # as within the current century
  copyright_line = first_lines[1]
  year = copyright_line[12:16]
  if is_newly_created and year != _current_year:
    raise HeaderCheckFailure(f'{filename}: copyright year must be {_current_year} (was {year})')
  elif not _current_century_regex.match(year):
    raise HeaderCheckFailure(
      f"{filename}: copyright year must match '{_current_century_regex.pattern}' (was {year}): " +
      f"current year is {_current_year}"
    )
  # Replace copyright_line with sanitized year.
  first_lines[1] = "# Copyright YYYY" + copyright_line[16:]
  if "".join(first_lines) != EXPECTED_HEADER:
    raise HeaderCheckFailure(f"{filename}: header does not match expected header")


def check_dir(directory: str, newly_created_files: Iterable[str]) -> List[str]:
  """Returns list of files that fail the check."""
  header_parse_failures = []
  for root, dirs, files in os.walk(directory):
    for f in files:
      if not f.endswith('.py') or os.path.basename(f) == '__init__.py':
        continue
      filename = os.path.join(root, f)
      try:
        check_header(filename, is_newly_created=filename in newly_created_files)
      except HeaderCheckFailure as e:
        header_parse_failures.append(str(e))
  return header_parse_failures


def main() -> None:
  dirs = sys.argv
  header_parse_failures = []
  # Input lines denote file paths relative to the repo root and are assumed to all end in \n.
  newly_created_files = frozenset((line[0:-1] for line in sys.stdin)
                                  if 'PANTS_IGNORE_ADDED_FILES' not in os.environ
                                  else [])

  for directory in dirs:
    header_parse_failures.extend(check_dir(directory, newly_created_files))
  if header_parse_failures:
    failures = '\n  '.join(header_parse_failures)
    raise SystemExit(f"""\
ERROR: All .py files other than __init__.py should start with the following header:

{EXPECTED_HEADER}
---

Some additional checking is performed on newly added files, such as validating the
copyright year. You can export PANTS_IGNORE_ADDED_FILES to disable this check.

The following {len(header_parse_failures)} file(s) do not conform:
{failures}""")


if __name__ == '__main__':
  main()
