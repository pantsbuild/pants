# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.common import Nit
from pants.contrib.python.checks.checker.implicit_string_concatenation import \
  ImplicitStringConcatenation


class ImplicitStringConcatenationTest(CheckstylePluginTestBase):
  plugin_type = ImplicitStringConcatenation

  def test_implicit_string_concatenation(self):
    self.assertNit("'a' 'b'", 'T806', Nit.WARNING)
    self.assertNit('"a" "b"', 'T806', Nit.WARNING)
    self.assertNit("'a' \"b\"", 'T806', Nit.WARNING)
    self.assertNit("('a'\n'b')", 'T806', Nit.WARNING)
    self.assertNit("('a''b')", 'T806', Nit.WARNING)
    self.assertNit("'a''b'", 'T806', Nit.WARNING)
    self.assertNit("'a \\'' 'b'", 'T806', Nit.WARNING)
    self.assertNoNits("'a' + 'b'")
    self.assertNoNits("('a' + 'b')")
    self.assertNoNits("'''hello!'''")
    self.assertNoNits('"""hello"""')

  def test_handles_inconsistent_indentation(self):
    multiline_multiple_indent_text = """\
        ("$(if [ -e ./{0} -a -e ./{1} ]; then echo 'mark_success'; "
         "elif [ -e ./{1} ]; then echo 'mark_failed'; "
        "else echo 'no_op'; fi)")"""
    self.assertNit(multiline_multiple_indent_text, 'T806', Nit.WARNING)

  def test_accepts_triple_quote_string(self):
    triple_quote_string = """\
\"\"\"
    Calculate the actual disk allocation for a file.  This works at least on OS X and
    Linux, but may not work on other systems with 1024-byte blocks (apparently HP-UX?)

    From pubs.opengroup.org:

    The unit for the st_blocks member of the stat structure is not defined
    within IEEE Std 1003.1-2001 / POSIX.1-2008.  In some implementations it
    is 512 bytes.  It may differ on a file system basis.  There is no
    correlation between values of the st_blocks and st_blksize, and the
    f_bsize (from <sys/statvfs.h>) structure members.
  \"\"\"
"""
    self.assertNoNits(triple_quote_string)
