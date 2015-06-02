#!/usr/bin/env python2.7
# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

#  Helper for check_headers.sh to check .py files in the repo to see if they start with the
# appropriate headers.
#
# usage: check_header_helper.py dir1 [ dir2 [ ... ] ]

import os
import re
import sys

EXPECTED_HEADER="""# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

"""


def check_header(filename):
  """Returns True if header check passes."""
  try:
    with open(filename, 'r') as pyfile:
      buf = ""
      for lineno in range(1,8):
        line = pyfile.readline()
        # Skip shebang line
        if lineno == 1 and line.startswith('#!'):
          line = pyfile.readline()
        # Don't care much about the actual year, just that its there
        if line.startswith("# Copyright"):
          year = line[12:-4]
          if not re.match(r'20\d\d', year):
            return False
          line = "# Copyright YYYY" + line[16:]
        buf += line
      return buf == EXPECTED_HEADER
  except IOError:
    return False

def check_dir(directory):
  """Returns list of files that fail the check."""
  failed_files = []
  for root, dirs, files in os.walk(directory):
    for f in files:
      if f.endswith('.py') and os.path.basename(f) != '__init__.py':
        filename = os.path.join(root, f)
        if not check_header(filename):
          failed_files.append(filename)
  return failed_files


def main():
  dirs = sys.argv
  failed_files = []
  for directory in dirs:
    failed_files.extend(check_dir(directory))
  if failed_files:
    print 'ERROR: All .py files other than __init__.py should start with the following header:'
    print
    print EXPECTED_HEADER
    print '---'
    print 'The following {} file(s) do not conform:'.format(len(failed_files))
    print '  {}'.format('\n  '.join(failed_files))
    sys.exit(1)

if __name__ == '__main__':
  main()
