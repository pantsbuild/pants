#!/usr/bin/env python2.7
# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import logging
import os
import re
import sys
from abc import abstractmethod, abstractproperty
from io import open

from twitter.common.collections import OrderedSet

from pants.util.dirutil import read_file
from pants.util.meta import AbstractClass, classproperty


#  Helper for check_headers.sh to check .py files in the repo to see if they start with the
# appropriate headers.
#
# usage: check_header_helper.py dir1 [ dir2 [ ... ] ]




logger = logging.getLogger(__name__)


# TODO: use AbstractClass and other pants utils which can be run from source by running in the pants
# venv!
class HeaderChecker(AbstractClass):

  @abstractmethod
  def matches_file_path(self, file_path):
    """

    :rtype: bool
"""

  @abstractmethod
  def do_header_check(self, filename, is_newly_created=False):
    """

    Raises `HeaderCheckFailure` if the header doesn't match.
    """

  class HeaderCheckFailure(Exception):
    """This is only used for control flow and to propagate the `.message` field."""

  _current_year = str(datetime.datetime.now().year)
  _current_century_regex = re.compile(r'20\d\d')

  @classmethod
  def check_copyright_year(cls, filename, year_string, is_newly_created):
    if not cls._current_century_regex.match(year_string):
      raise cls.HeaderCheckFailure(
        "{}: copyright year must match '{}' (was {}): current year is {}"
        .format(filename, cls._current_century_regex.pattern, year_string, cls._current_year))
    if is_newly_created and year_string != cls._current_year:
      raise cls.HeaderCheckFailure('{}: copyright year must be {} (was {})'
                                   .format(filename, cls._current_year, year_string))

  # TODO!!!
  @classproperty
  @abstractproperty
  def help_message_on_failure(cls):
    """???"""


class BUILDFileHeaderChecker(HeaderChecker):

  # TODO: figure out how to avoid manually escaping by using re.escape() and format()!
  _header_pattern = re.compile("""\
# Copyright ([0-9]+) Pants project contributors \\(see CONTRIBUTORS\\.md\\)\\.
# Licensed under the Apache License, Version 2\\.0 \\(see LICENSE\\)\\.
""")

  help_message_on_failure = """\
All BUILD files must start with a header matching the following regular expression:
{}""".format(_header_pattern.pattern)

  def matches_file_path(self, file_path):
    return os.path.basename(file_path).startswith('BUILD')

  def do_header_check(self, filename, is_newly_created=False):
    file_contents = read_file(filename, binary_mode=False)
    header_result = self._header_pattern.match(file_contents)
    if not header_result:
      raise self.HeaderCheckFailure('{}: failed to parse BUILD file header'.format(filename))
    copyright_year = header_result.group(1)
    self.check_copyright_year(filename=filename,
                              year_string=copyright_year,
                              is_newly_created=is_newly_created)


class PythonSourceHeaderChecker(HeaderChecker):

  _EXPECTED_HEADER="""# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals
"""

  help_message_on_failure = """\
All .py files other than __init__.py should start with the following header:\n{}\
""".format(_EXPECTED_HEADER)

  def matches_file_path(self, file_path):
    return file_path.endswith('.py') and os.path.basename(file_path) != '__init__.py'

  def do_header_check(self, filename, is_newly_created=False):
    # TODO: do some real parsing instead of letting each checker figure out how to iterate over a
    # live file handle!
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
          self.check_copyright_year(filename=filename,
                                    year_string=year,
                                    is_newly_created=is_newly_created)
          line = "# Copyright YYYY" + line[16:]
        buf += line

      # NB: Replace any repeated trailing newlines with a single one. This can occur when we read to
      # line 7 in a file without a shebang line.
      buf = re.sub('\n+$', '\n', buf)
      if buf != self._EXPECTED_HEADER:
        logger.debug("generated `buf`: {}".format(buf))
        raise self.HeaderCheckFailure('{}: failed to parse python file header!'
                                      .format(filename))


def check_dir(directory, newly_created_files, header_checkers):
  """Returns list of files that fail the check."""
  failing_header_checkers = OrderedSet()
  header_parse_failures = []
  for root, dirs, files in os.walk(directory):
    for f in files:
      for checker in header_checkers:
        full_filename = os.path.join(root, f)
        if checker.matches_file_path(full_filename):
          is_newly_created = full_filename in newly_created_files
          try:
            checker.do_header_check(full_filename, is_newly_created=is_newly_created)
          except IOError as e:
            header_parse_failures.append(
              '{}: error while reading input ({})'
              .format(full_filename, str(e)))
          except HeaderChecker.HeaderCheckFailure as e:
            failing_header_checkers.add(checker)
            header_parse_failures.append(str(e))
  # Get the help messages from each checker which reported an error checking the file's header.
  checker_help_messages = [checker.help_message_on_failure for checker in failing_header_checkers]
  return header_parse_failures, checker_help_messages


def main():
  dirs = sys.argv[1:]
  # Input lines denote file paths relative to the repo root and are assumed to all end in \n.
  newly_created_files = frozenset((line[0:-1] for line in sys.stdin)
                                  if 'PANTS_IGNORE_ADDED_FILES' not in os.environ
                                  else [])
  header_checkers = [
    BUILDFileHeaderChecker(),
    PythonSourceHeaderChecker(),
  ]

  header_parse_failures = []
  checker_help_messages = []

  for directory in dirs:
    parse_failures, help_messages = check_dir(directory, newly_created_files, header_checkers)
    header_parse_failures.extend(parse_failures)
    checker_help_messages.extend(help_messages)
  if header_parse_failures:
    msg = ("""Errors encountered checking headers!
{help_messages}Some additional checking is performed on newly added files, such as validating the \
copyright year.
You can export PANTS_IGNORE_ADDED_FILES to disable this check.
The following {num_files} file(s) do not conform:
{error_messages}
""".format(help_messages=('Help:\n{}\n'
                          .format('\n------\n'.join(msg for msg in checker_help_messages))
                          if checker_help_messages else ''),
           num_files=len(header_parse_failures),
           error_messages='\n'.join('  {}'.format(line) for line in header_parse_failures)))
    print(msg, file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
  main()
