#!/usr/bin/env python
# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

#  Helper for check_headers.sh to check .py files in the repo to see if they start with the
# appropriate headers.
#
# usage: check_header_helper.py dir1 [ dir2 [ ... ] ]

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import re
import sys
from io import open

EXPECTED_HEADER="""# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

"""


_current_year = str(datetime.datetime.now().year)


_current_century_regex = re.compile(r'20\d\d')


class HeaderCheckFailure(Exception):
  """This is only used for control flow and to propagate the `.message` field."""


def check_header(filename, is_newly_created=False):
  """Raises `HeaderCheckFailure` if the header doesn't match."""
  try:
    with open(filename, 'r') as pyfile:
      buf = ""
      for lineno in range(1,7):
        line = pyfile.readline()
        # Skip shebang line
        if lineno == 1 and line.startswith('#!'):
          line = pyfile.readline()
        # Check if the copyright year can be parsed as within the current century, or the current
        # year if it is a new file.
        if line.startswith("# Copyright"):
          year = line[12:16]
          if is_newly_created:
            if not year == _current_year:
              raise HeaderCheckFailure('{}: copyright year must be {} (was {})'
                                       .format(filename, _current_year, year))
          else:
            if not _current_century_regex.match(year):
              raise HeaderCheckFailure(
                "{}: copyright year must match '{}' (was {}): current year is {}"
                .format(filename, _current_century_regex.pattern, year, _current_year))
          line = "# Copyright YYYY" + line[16:]
        buf += line
      if buf != EXPECTED_HEADER:
        raise HeaderCheckFailure('{}: failed to parse header at all'
                                 .format(filename))
  except IOError as e:
    raise HeaderCheckFailure('{}: error while reading input ({})'
                             .format(filename, str(e)))


def check_dir(directory, newly_created_files):
  """Returns list of files that fail the check."""
  header_parse_failures = []
  for root, dirs, files in os.walk(directory):
    for f in files:
      if f.endswith('.py') and os.path.basename(f) != '__init__.py':
        filename = os.path.join(root, f)
        try:
          check_header(filename, filename in newly_created_files)
        except HeaderCheckFailure as e:
          header_parse_failures.append(e.message)
  return header_parse_failures


def main():
  dirs = sys.argv
  header_parse_failures = []
  # Input lines denote file paths relative to the repo root and are assumed to all end in \n.
  newly_created_files = frozenset((line[0:-1] for line in sys.stdin)
                                  if 'PANTS_IGNORE_ADDED_FILES' not in os.environ
                                  else [])

  for directory in dirs:
    header_parse_failures.extend(check_dir(directory, newly_created_files))
  if header_parse_failures:
    print('ERROR: All .py files other than __init__.py should start with the following header:')
    print()
    print(EXPECTED_HEADER)
    print('---')
    print('Some additional checking is performed on newly added files, such as \n'
          'validating the copyright year. You can export PANTS_IGNORE_ADDED_FILES to disable this check.')
    print('The following {} file(s) do not conform:'.format(len(header_parse_failures)))
    print('  {}'.format('\n  '.join(header_parse_failures)))
    sys.exit(1)


if __name__ == '__main__':
  main()
