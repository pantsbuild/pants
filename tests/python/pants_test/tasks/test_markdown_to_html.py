# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.core.tasks import markdown_to_html


ABC = """able
baker
charlie"""


class ChooseLinesTest(unittest.TestCase):
  def test_include_no_params(self):
    self.assertEquals(
        markdown_to_html.choose_include_text(ABC, '', 'fake.md'),
        '\n'.join(['able', 'baker', 'charlie']))

  def test_include_start_at(self):
    self.assertEquals(
        markdown_to_html.choose_include_text(ABC, 'start-at=abl', 'fake.md'),
        '\n'.join(['able', 'baker', 'charlie']))

    self.assertEquals(
        markdown_to_html.choose_include_text(ABC, 'start-at=bak', 'fake.md'),
        '\n'.join(['baker', 'charlie']))

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-at=xxx', 'fake.md'),
      '')

  def test_include_start_after(self):
    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-after=bak', 'fake.md'),
      'charlie')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-after=cha', 'fake.md'),
      '')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-after=xxx', 'fake.md'),
      '')

  def test_include_end_at(self):
    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-at=abl', 'fake.md'),
      'able')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-at=bak', 'fake.md'),
      '\n'.join(['able', 'baker']))

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-at=xxx', 'fake.md'),
      '')

  def test_include_end_before(self):
    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-before=abl', 'fake.md'),
      '')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-before=xxx', 'fake.md'),
      '')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'end-before=bak', 'fake.md'),
      'able')

  def test_include_start_at_end_at(self):
    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-at=abl&end-at=abl', 'fake.md'),
      'able')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-at=cha&end-at=cha', 'fake.md'),
      'charlie')

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-at=abl&end-at=bak', 'fake.md'),
      '\n'.join(['able', 'baker']))

    self.assertEquals(
      markdown_to_html.choose_include_text(ABC, 'start-at=bak&end-at=abl', 'fake.md'),
      '')
