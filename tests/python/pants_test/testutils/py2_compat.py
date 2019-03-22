# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import PY3


def assertRegex(self, text, expected_regex, msg=None):
  """Call unit test assertion to ensure regex matches.

  While Py3 still has assertRegexpMatches, it's deprecated. This function also exists for consistency with
  our helper function assertNotRegex, which *is* required for Py2-3 compatibility.
  """
  if PY3:
    self.assertRegex(text, expected_regex, msg)
  else:
    self.assertRegexpMatches(text, expected_regex, msg)


def assertNotRegex(self, text, unexpected_regex, msg=None):
  """Call unit test assertion to ensure regex does not match.

  Required for compatibility because Py3.4 does not have assertNotRegexpMatches.
  """
  if PY3:
    self.assertNotRegex(text, unexpected_regex, msg)
  else:
    self.assertNotRegexpMatches(text, unexpected_regex, msg)
