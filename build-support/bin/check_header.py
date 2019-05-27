#!/usr/bin/env python3
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import datetime
import os
import re
from abc import abstractmethod, abstractproperty
from textwrap import dedent
from typing import Iterable, List

from twitter.common.collections import OrderedSet

from pants.util.dirutil import read_file
from pants.util.meta import AbstractClass, classproperty

from common import die


# TODO: use AbstractClass and other pants utils which can be run from source by running in the pants
# venv!
class HeaderChecker(AbstractClass):

  @abstractmethod
  def matches_file_path(self, file_path) -> bool:
    pass

  @abstractmethod
  def do_header_check(self, filename, is_newly_created=False):
    """Raises `HeaderCheckFailure` if the header doesn't match."""

  class HeaderCheckFailure(Exception):
    """This is only used for control flow and to propagate the `.message` field."""

  _current_year = str(datetime.datetime.now().year)
  _current_century_regex = re.compile(r'20\d\d')

  @classmethod
  def check_copyright_year(cls, filename, year_string, is_newly_created):
    """Check that copyright is current year if for a new file, else that it's within
    the current century."""
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

  @abstractproperty
  @classproperty
  def expected_header(cls):
    """???"""

  @abstractproperty
  @classproperty
  def python_source_description(cls):
    """???"""

  @classproperty
  def help_message_on_failure(cls):
    return (
      "All {} files other than __init__.py should start with the following header:\n{}"
      .format(cls.python_source_description, cls.expected_header))

  @abstractproperty
  @classproperty
  def expected_header_lines(cls):
    """???"""

  @abstractproperty
  @classproperty
  def copyright_line_index(cls):
    """???"""

  _MAX_POSSIBLE_HEADER_LINES = 6

  @classmethod
  def _get_header_lines(cls, filename: str) -> List[str]:
    try:
      with open(filename, 'r') as f:
        # We grab an extra line in case there is a shebang.
        lines = [f.readline() for _ in range(0, cls._MAX_POSSIBLE_HEADER_LINES + 1)]
    except IOError as e:
      raise HeaderCheckFailure(f"{filename}: error while reading input ({e})")
    # If a shebang line is included, remove it. Otherwise, we will have conservatively grabbed
    # one extra line at the end for the shebang case that is no longer necessary.
    lines.pop(0 if lines[0].startswith("#!") else - 1)
    return lines

  @classmethod
  def _is_py3(cls, file_path: str) -> bool:
    lines = cls._get_header_lines(file_path)
    return all("from __future__" not in line for line in lines)

  def matches_file_path(self, file_path: str) -> bool:
    return file_path.endswith('.py') and os.path.basename(file_path) != '__init__.py'

  def do_header_check(self, filename, is_newly_created=False):
    lines = self._get_header_lines(filename)
    if len([line for line in lines if line]) < self.expected_header_lines:
      raise HeaderCheckFailure(f"{filename}: missing the expected header")
    lines = lines[:self.expected_header_lines]

    copyright_line = lines[self.copyright_line_index]
    year_string = copyright_line[12:16]
    self.check_copyright_year(
      filename=filename,
      year_string=year_string,
      is_newly_created=is_newly_created)

    lines[self.copyright_line_index] = "# Copyright YYYY" + copyright_line[16:]
    if ''.join(lines) != self.expected_header:
      raise HeaderCheckFailure(f"{filename}: header does not match the expected header")


class Python2Checker(PythonSourceHeaderChecker):

  expected_header = dedent("""\
    # coding=utf-8
    # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
    # Licensed under the Apache License, Version 2.0 (see LICENSE).

    from __future__ import absolute_import, division, print_function, unicode_literals

    """)

  expected_header_lines = 6
  copyright_line_index = 1

  python_source_description = 'python 2 source files'

  def matches_file_path(self, file_path):
    return super(Python2Checker, self).matches_file_path(file_path) and not self._is_py3(file_path)


class Python3Checker(PythonSourceHeaderChecker):

  expected_header = dedent("""\
    # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
    # Licensed under the Apache License, Version 2.0 (see LICENSE).

    """)

  expected_header_lines = 3
  copyright_line_index = 0

  python_source_description = 'python 3 source files'

  def matches_file_path(self, file_path):
    return super(Python3Checker, self).matches_file_path(file_path) and self._is_py3(file_path)


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


def main() -> None:
  args = create_parser().parse_args()
  dirs = args.dirs
  newly_created_files = frozenset(args.newly_created_files
                                  if 'PANTS_IGNORE_ADDED_FILES' not in os.environ
                                  else [])

  header_parse_failures = []
  checker_help_messages = []

  header_checkers = [
    BUILDFileHeaderChecker(),
    Python2Checker(),
    Python3Checker(),
  ]

  for directory in dirs:
    parse_failures, help_messages = check_dir(
      directory, newly_created_files, header_checkers)
    header_parse_failures.extend(parse_failures)
    checker_help_messages.extend(help_messages)

  if header_parse_failures:
    die(dedent("""\
      Errors encountered checking headers!
      {help_messages}Some additional checking is performed on newly added files, such as validating the copyright year.
      You can export PANTS_IGNORE_ADDED_FILES to disable this check.
      The following {num_files} file(s) do not conform:
      {error_messages}
      """.format(help_messages=('Help:\n{}\n'
                          .format('\n------\n'.join(msg for msg in checker_help_messages))
                          if checker_help_messages else ''),
           num_files=len(header_parse_failures),
           error_messages='\n'.join('  {}'.format(line) for line in header_parse_failures))))


def create_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Check that all .py files start with the appropriate header."
  )
  parser.add_argument("dirs", nargs="+",
    help="The directories to check. Will recursively check subdirectories."
  )
  parser.add_argument("-a", "--newly-created-files", nargs="*", default=[],
    help="Any passed files will be checked for a current copyright year."
  )
  return parser


if __name__ == '__main__':
  main()
