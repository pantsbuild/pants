# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest2 as unittest

from pants.backend.core.tasks import markdown_to_html

ABC = """able
baker
charlie"""


class ChooseLinesTest(unittest.TestCase):
  def test_include_no_params(self):
    self.assertEquals(
        markdown_to_html.choose_include_lines(ABC, '', 'fake.md'),
        ['able', 'baker', 'charlie'])

  def test_include_start_at(self):
    self.assertEquals(
        markdown_to_html.choose_include_lines(ABC, 'start-at=abl', 'fake.md'),
        ['able', 'baker', 'charlie'])

    self.assertEquals(
        markdown_to_html.choose_include_lines(ABC, 'start-at=bak', 'fake.md'),
        ['baker', 'charlie'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-at=xxx', 'fake.md'),
      [])

  def test_include_start_after(self):
    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-after=bak', 'fake.md'),
      ['charlie'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-after=cha', 'fake.md'),
      [])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-after=xxx', 'fake.md'),
      [])

  def test_include_end_at(self):
    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-at=abl', 'fake.md'),
      ['able'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-at=bak', 'fake.md'),
      ['able', 'baker'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-at=xxx', 'fake.md'),
      [])

  def test_include_end_before(self):
    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-before=abl', 'fake.md'),
      [])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-before=xxx', 'fake.md'),
      [])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'end-before=bak', 'fake.md'),
      ['able'])

  def test_include_start_at_end_at(self):
    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-at=abl&end-at=abl', 'fake.md'),
      ['able'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-at=cha&end-at=cha', 'fake.md'),
      ['charlie'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-at=abl&end-at=bak', 'fake.md'),
      ['able', 'baker'])

    self.assertEquals(
      markdown_to_html.choose_include_lines(ABC, 'start-at=bak&end-at=abl', 'fake.md'),
      [])
