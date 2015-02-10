# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from argparse import ArgumentParser

from pants.option.help_formatter import PantsAdvancedHelpFormatter, PantsBasicHelpFormatter


class OptionHelpFormatterTest(unittest.TestCase):
  def test_suppress_advanced(self):
    argparser = ArgumentParser(formatter_class=PantsBasicHelpFormatter)
    group = argparser.add_argument_group(title='foo')
    advanced_group = argparser.add_argument_group(title='*foo')
    group.add_argument('--bar', help='help for argument bar')
    advanced_group.add_argument('--baz', help='help for argument baz')

    help_output = argparser.format_help()
    self.assertIn('--bar', help_output)
    self.assertNotIn('(ADVANCED)', help_output)
    self.assertNotIn('--baz', help_output)

    argparser = ArgumentParser(formatter_class=PantsAdvancedHelpFormatter)
    help_output = argparser.format_help()
    self.assertIn('--bar', help_output)
    self.assertIn('(ADVANCED)', help_output)
    self.assertIn('--baz', help_output)
