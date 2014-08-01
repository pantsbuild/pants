# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import argparse


class PantsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
  """A custom argparse help formatter subclass.

  Squelches extraneous text, such as usage messages and section headers, because
  we format those ourselves.  Leaves just the actual flag help.
  """
  def add_usage(self, usage, actions, groups, prefix=None):
    pass

  def add_text(self, text):
    pass

  def start_section(self, heading):
    pass

  def end_section(self):
    pass
