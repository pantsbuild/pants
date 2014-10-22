# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
from textwrap import dedent
import os
import unittest2 as unittest

from pants.base.rcfile import RcFile
from pants.util.contextutil import temporary_file


class ParseSpecTest(unittest.TestCase):
  def test_parse_rcfile(self):
    with temporary_file() as rc:
      rc.write(dedent("""
      [jvm]
      options: --compile-java-args='-target 7 -source 7'
      """))
      rc.close()
      rcfile = RcFile([rc.name], default_prepend=False)
      commands = ['jvm', 'fleem']
      args = ['javac', 'Foo.java']
      new_args = rcfile.apply_defaults(commands, args)
      self.assertEquals(['javac', 'Foo.java', '--compile-java-args=-target 7 -source 7'], new_args)
