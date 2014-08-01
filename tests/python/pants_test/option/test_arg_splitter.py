# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest
import shlex
import unittest

from twitter.common.lang import Compatibility

from pants.option.arg_splitter import ArgSplitter, ArgSplitterError


class ArgSplitterTest(unittest.TestCase):
  _known_scopes = ['compile', 'compile.java', 'compile.scala', 'test', 'test.junit']

  def _split(self, args, expected_scope_to_flags, expected_target_specs, expected_help=False):
    splitter = ArgSplitter(ArgSplitterTest._known_scopes)
    if isinstance(args, Compatibility.string):
      args = shlex.split(str(args))
    scope_to_flags, target_specs = splitter.split_args(args)
    self.assertEquals(expected_scope_to_flags, scope_to_flags)
    self.assertEquals(expected_target_specs, target_specs)
    self.assertEquals(expected_help, splitter.is_help)

  def _error_split(self, args):
    parser = ArgSplitter(ArgSplitterTest._known_scopes)
    if isinstance(args, Compatibility.string):
      args = shlex.split(str(args))
    with pytest.raises(ArgSplitterError):
      parser.split_args(args)

  def test_arg_splitting(self):
    # Various flag combos.
    self._split('./pants', {'': []}, [])
    self._split('./pants goal', {'': []}, [])
    self._split('./pants -f', {'': ['-f']}, [])
    self._split('./pants goal -f', {'': ['-f']}, [])
    self._split('./pants -f compile -g compile.java -x test.junit -i '
                'src/java/com/pants/foo src/java/com/pants/bar:baz',
                {'': ['-f'], 'compile': ['-g'], 'compile.java': ['-x'], 'test.junit': ['-i']},
                ['src/java/com/pants/foo', 'src/java/com/pants/bar:baz'])
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                'src/java/com/pants/foo src/java/com/pants/bar:baz',
                {
                  '': ['-farg', '--fff=arg'],
                  'compile': ['--gg-gg=arg-arg', '-g'],
                 'test.junit': ['--iii']
                },
                ['src/java/com/pants/foo', 'src/java/com/pants/bar:baz'])

    # Distinguishing goals and target specs.
    self._split('./pants compile test foo::', {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile test -- foo::', {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile -- test', {'': [], 'compile': []}, ['test'])
    self._split('./pants test -- test', {'': [], 'test': []}, ['test'])

    # Flags where only target specs should be.
    self._error_split('./pants compile -- -f')
    self._error_split('./pants compile -- foo/bar --flag')

  def test_help_detection(self):
    self._split('./pants help', {'': []}, [], True)
    self._split('./pants goal help', {'': []}, [], True)
    self._split('./pants -h', {'': []}, [], True)
    self._split('./pants goal -h', {'': []}, [], True)
    self._split('./pants --help', {'': []}, [], True)
    self._split('./pants goal --help', {'': []}, [], True)
    self._split('./pants help compile -x', {'': [], 'compile': ['-x']}, [], True)
    self._split('./pants help compile -x', {'': [], 'compile': ['-x']}, [], True)
    self._split('./pants compile -h', {'': [], 'compile': []}, [], True)
    self._split('./pants compile --help test', {'': [], 'compile': [], 'test': []}, [], True)
