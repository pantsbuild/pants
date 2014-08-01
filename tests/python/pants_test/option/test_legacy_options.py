# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import optparse
import pytest
import shlex
import unittest

from pants.option.legacy_options import LegacyOptions


class LegacyOptionsTest(unittest.TestCase):
  def test_registration(self):
    optparser = optparse.OptionParser()
    legacy_options = LegacyOptions('compile.java', optparser)
    legacy_options.register(['--foo'], { 'action': 'store_true' }, 'compile_java_foo')
    legacy_options.register(['--bar'], { 'type': long }, 'compile_java_bar')
    legacy_options.register(['--baz'], { 'choices': ['xx', 'yy', 'zz'] }, 'compile_java_baz')
    legacy_options.register(['--qux'], { 'type': int, 'choices': [1, 2, 3], 'action': 'append' },
                            'compile_java_qux')
    legacy_options.register(['--corge'], { 'type': int, 'default': 55 } ,
                            'compile_java_corge')

    args = shlex.split(str('--compile-java-foo --compile-java-bar=33 --compile-java-baz=xx '
                           '--compile-java-qux=1 --compile-java-qux=4'))
    opts, _ = optparser.parse_args(args)
    self.assertTrue(opts.compile_java_foo)
    self.assertEquals(opts.compile_java_bar, 33)
    self.assertEquals(opts.compile_java_baz, 'xx')
    self.assertEquals(opts.compile_java_qux, [1, 4])  # Choices not enforced for non-string types.
    self.assertEquals(opts.compile_java_corge, 55)  # Defaults preserved.

    with pytest.raises(SystemExit):
      args = shlex.split(str('--compile-java-baz=ww'))  # Choices enforced for string types.
      opts, _ = optparser.parse_args(args)
