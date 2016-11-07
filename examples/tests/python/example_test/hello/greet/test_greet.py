# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from example.hello.greet.greet import greet


class GreetTest(unittest.TestCase):
  def test_greeting_mentions_addressee(self):
    """Fancy formatting should not omit the person we're greeting"""
    assert('foo' in greet('foo'))

  def test_prereq_run(self):
    # This file is created by the prep_command in the BUILD file
    os.unlink("/tmp/prep_command_result")
