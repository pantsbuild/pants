# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex
import unittest2 as unittest

from pants.option.arg_splitter import ArgSplitter


class ArgSplitterTest(unittest.TestCase):
  _known_scopes = ['compile', 'compile.java', 'compile.scala', 'test', 'test.junit']

  def _split(self, args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
             expected_passthru=None, expected_passthru_owner=None, expected_is_help=False):
    expected_passthru = expected_passthru or []
    splitter = ArgSplitter(ArgSplitterTest._known_scopes)
    args = shlex.split(str(args_str))
    goals, scope_to_flags, target_specs, passthru, passthru_owner = splitter.split_args(args)
    self.assertEquals(expected_goals, goals)
    self.assertEquals(expected_scope_to_flags, scope_to_flags)
    self.assertEquals(expected_target_specs, target_specs)
    self.assertEquals(expected_passthru, passthru)
    self.assertEquals(expected_passthru_owner, passthru_owner)
    self.assertEquals(expected_is_help, splitter.is_help)

  def test_arg_splitting(self):
    # Various flag combos.
    self._split('./pants', [], {'': []}, [])
    self._split('./pants goal', [], {'': []}, [])
    self._split('./pants -f', [], {'': ['-f']}, [])
    self._split('./pants goal -f', [], {'': ['-f']}, [])
    self._split('./pants --compile-java-long-flag -f compile -g compile.java -x test.junit -i '
                'src/java/com/pants/foo src/java/com/pants/bar:baz',
                ['compile', 'test'],
                {
                  '': ['-f'],
                  'compile.java': ['--long-flag', '-x'],
                  'compile': ['-g'],
                  'test.junit': ['-i']
                },
                ['src/java/com/pants/foo', 'src/java/com/pants/bar:baz'])
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                '--compile-java-long-flag src/java/com/pants/foo src/java/com/pants/bar:baz',
                ['compile', 'test'],
                {
                  '': ['-farg', '--fff=arg'],
                  'compile': ['--gg-gg=arg-arg', '-g'],
                  'test.junit': ['--iii'],
                  'compile.java': ['--long-flag'],
                },
                ['src/java/com/pants/foo', 'src/java/com/pants/bar:baz'])

    # Distinguishing goals and target specs.
    self._split('./pants compile test foo::', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile test foo::', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile test:test', ['compile'], {'': [], 'compile': []}, ['test:test'])
    self._split('./pants test test:test', ['test'], {'': [], 'test': []}, ['test:test'])
    self._split('./pants test ./test', ['test'], {'': [], 'test': []}, ['./test'])
    self._split('./pants test //test', ['test'], {'': [], 'test': []}, ['//test'])

    # De-scoping old-style flags correctly.
    self._split('./pants compile test --compile-java-bar --no-test-junit-baz foo',
                ['compile', 'test'],
                {'': [], 'compile': [], 'compile.java': ['--bar'], 'test': [],
                 'test.junit': ['--no-baz']}, ['foo'])

    # Old-style flags don't count as explicit goals.
    self._split('./pants compile --test-junit-bar foo',
                ['compile'],
                {'': [], 'compile': [], 'test.junit': ['--bar']}, ['foo'])

    # Passthru args.
    self._split('./pants test foo -- -t arg',
                ['test'],
                {'': [], 'test': []},
                ['foo'],
                expected_passthru=['-t', 'arg'],
                expected_passthru_owner='test')
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                '--compile-java-long-flag src/java/com/pants/foo src/java/com/pants/bar:baz '
                '-- passthru1 passthru2',
                ['compile', 'test'],
                {
                  '': ['-farg', '--fff=arg'],
                  'compile': ['--gg-gg=arg-arg', '-g'],
                  'compile.java': ['--long-flag'],
                  'test.junit': ['--iii']
                },
                ['src/java/com/pants/foo', 'src/java/com/pants/bar:baz'],
                expected_passthru=['passthru1', 'passthru2'],
                expected_passthru_owner='test.junit')

  def test_help_detection(self):
    self._split('./pants help', ['help'], {'': []}, [], [], expected_is_help=True)
    self._split('./pants goal help', ['help'], {'': []}, [], [], expected_is_help=True)
    self._split('./pants -h', [], {'': []}, [], [], expected_is_help=True)
    self._split('./pants goal -h', [], {'': []}, [], [], expected_is_help=True)
    self._split('./pants --help', [], {'': []}, [], [], expected_is_help=True)
    self._split('./pants goal --help', [], {'': []}, [], [], expected_is_help=True)
    self._split('./pants help compile -x', ['help', 'compile'],
                {'': [], 'compile': ['-x']}, [], [], expected_is_help=True)
    self._split('./pants help compile -x', ['help', 'compile'],
                {'': [], 'compile': ['-x']}, [], [], expected_is_help=True)
    self._split('./pants compile -h', ['compile'],
                {'': [], 'compile': []}, [], [], expected_is_help=True)
    self._split('./pants compile --help test', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, [], [], expected_is_help=True)
    self._split('./pants test src/foo/bar:baz -h', ['test'],
                {'': [], 'test': []}, ['src/foo/bar:baz'], [], expected_is_help=True)
