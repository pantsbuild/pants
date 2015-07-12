# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import shlex
import unittest

from pants.option.arg_splitter import ArgSplitter
from pants.option.scope import ScopeInfo


def goal(scope):
  return ScopeInfo(scope, ScopeInfo.GOAL)

def task(scope):
  return ScopeInfo(scope, ScopeInfo.TASK)

def global_subsys(scope):
  return ScopeInfo(scope, ScopeInfo.GLOBAL_SUBSYSTEM)

def task_subsys(scope):
  return ScopeInfo(scope, ScopeInfo.TASK_SUBSYSTEM)


class ArgSplitterTest(unittest.TestCase):
  _known_scope_infos = [goal('compile'), task('compile.java'), task('compile.scala'),
                        global_subsys('jvm'), task_subsys('jvm.test.junit'),
                        global_subsys('reporting'), goal('test'), task('test.junit')]

  def _split(self, args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
             expected_passthru=None, expected_passthru_owner=None,
             expected_is_help=False, expected_help_advanced=False, expected_help_all=False):
    expected_passthru = expected_passthru or []
    splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
    args = shlex.split(args_str)
    goals, scope_to_flags, target_specs, passthru, passthru_owner = splitter.split_args(args)
    self.assertEquals(expected_goals, goals)
    self.assertEquals(expected_scope_to_flags, scope_to_flags)
    self.assertEquals(expected_target_specs, target_specs)
    self.assertEquals(expected_passthru, passthru)
    self.assertEquals(expected_passthru_owner, passthru_owner)
    self.assertEquals(expected_is_help, splitter.help_request is not None)
    self.assertEquals(expected_help_advanced,
                      splitter.help_request is not None and splitter.help_request.advanced)
    self.assertEquals(expected_help_all,
                      splitter.help_request is not None and splitter.help_request.all_scopes)
    self.assertFalse(splitter.help_request is not None and splitter.help_request.version)

  def _split_help(self, args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
                  expected_help_advanced=False, expected_help_all=False):
    self._split(args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
                expected_passthru=None, expected_passthru_owner=None,
                expected_is_help=True,
                expected_help_advanced=expected_help_advanced,
                expected_help_all=expected_help_all)

  def _split_version(self, args_str):
    splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
    args = shlex.split(args_str)
    splitter.split_args(args)
    self.assertTrue(splitter.help_request is not None and splitter.help_request.version)

  def test_basic_arg_splitting(self):
    # Various flag combos.
    self._split('./pants --compile-java-long-flag -f compile -g compile.java -x test.junit -i '
                'src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz',
                ['compile', 'test'],
                {
                  '': ['-f'],
                  'compile.java': ['--long-flag', '-x'],
                  'compile': ['-g'],
                  'test.junit': ['-i']
                },
                ['src/java/org/pantsbuild/foo', 'src/java/org/pantsbuild/bar:baz'])
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                '--compile-java-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz',
                ['compile', 'test'],
                {
                  '': ['-farg', '--fff=arg'],
                  'compile': ['--gg-gg=arg-arg', '-g'],
                  'test.junit': ['--iii'],
                  'compile.java': ['--long-flag'],
                },
                ['src/java/org/pantsbuild/foo', 'src/java/org/pantsbuild/bar:baz'])

  def test_distinguish_goals_from_target_specs(self):
    self._split('./pants compile test foo::', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile test foo::', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, ['foo::'])
    self._split('./pants compile test:test', ['compile'], {'': [], 'compile': []}, ['test:test'])
    self._split('./pants test test:test', ['test'], {'': [], 'test': []}, ['test:test'])
    self._split('./pants test ./test', ['test'], {'': [], 'test': []}, ['./test'])
    self._split('./pants test //test', ['test'], {'': [], 'test': []}, ['//test'])

  def test_descoping_qualified_flags(self):
    self._split('./pants compile test --compile-java-bar --no-test-junit-baz foo',
                ['compile', 'test'],
                {'': [], 'compile': [], 'compile.java': ['--bar'], 'test': [],
                 'test.junit': ['--no-baz']}, ['foo'])

    # Qualified flags don't count as explicit goals.
    self._split('./pants compile --test-junit-bar foo',
                ['compile'],
                {'': [], 'compile': [], 'test.junit': ['--bar']}, ['foo'])

  def test_passthru_args(self):
    self._split('./pants test foo -- -t arg',
                ['test'],
                {'': [], 'test': []},
                ['foo'],
                expected_passthru=['-t', 'arg'],
                expected_passthru_owner='test')
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                '--compile-java-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz '
                '-- passthru1 passthru2',
                ['compile', 'test'],
                {
                  '': ['-farg', '--fff=arg'],
                  'compile': ['--gg-gg=arg-arg', '-g'],
                  'compile.java': ['--long-flag'],
                  'test.junit': ['--iii']
                },
                ['src/java/org/pantsbuild/foo', 'src/java/org/pantsbuild/bar:baz'],
                expected_passthru=['passthru1', 'passthru2'],
                expected_passthru_owner='test.junit')

  def test_subsystem_flags(self):
    # Global subsystem flag in global scope.
    self._split('./pants --jvm-options=-Dbar=baz test foo',
                ['test'],
                {'': [], 'jvm': ['--options=-Dbar=baz'], 'test': []}, ['foo'])
    # Qualified task subsystem flag in global scope.
    self._split('./pants --jvm-test-junit-options=-Dbar=baz test foo',
                ['test'],
                {'': [], 'jvm.test.junit': ['--options=-Dbar=baz'], 'test': []}, ['foo'])
    # Unqualified task subsystem flag in task scope.
    self._split('./pants test.junit --jvm-options=-Dbar=baz foo',
                ['test'],
                {'': [], 'jvm.test.junit': ['--options=-Dbar=baz'], 'test.junit': []}, ['foo'])
    # Global-only flag in task scope.
    self._split('./pants test.junit --reporting-template-dir=path foo',
                ['test'],
                {'': [], 'reporting': ['--template-dir=path'], 'test.junit': []}, ['foo'])

  def test_help_detection(self):
    self._split_help('./pants', [], {'': []}, [])
    self._split_help('./pants goal', [], {'': []}, [])
    self._split_help('./pants -f', [], {'': ['-f']}, [])
    self._split_help('./pants goal -f', [], {'': ['-f']}, [])
    self._split_help('./pants help', [], {'': []}, [])
    self._split_help('./pants goal help', [], {'': []}, [])
    self._split_help('./pants -h', [], {'': []}, [])
    self._split_help('./pants goal -h', [], {'': []}, [])
    self._split_help('./pants --help', [], {'': []}, [])
    self._split_help('./pants goal --help', [], {'': []}, [])
    self._split_help('./pants help compile -x', ['compile'],
                {'': [], 'compile': ['-x']}, [])
    self._split_help('./pants help compile -x', ['compile'],
                {'': [], 'compile': ['-x']}, [])
    self._split_help('./pants compile -h', ['compile'],
                {'': [], 'compile': []}, [])
    self._split_help('./pants compile --help test', ['compile', 'test'],
                {'': [], 'compile': [], 'test': []}, [])
    self._split_help('./pants test src/foo/bar:baz -h', ['test'],
                {'': [], 'test': []}, ['src/foo/bar:baz'])

    self._split_help('./pants help-advanced', [], {'': []}, [], True, False)
    self._split_help('./pants help-all', [], {'': []}, [], False, True)
    self._split_help('./pants --help-advanced', [], {'': []}, [], True, False)
    self._split_help('./pants --help-all', [], {'': []}, [], False, True)
    self._split_help('./pants --help --help-advanced', [], {'': []}, [], True, False)
    self._split_help('./pants --help-advanced --help', [], {'': []}, [], True, False)
    self._split_help('./pants --help --help-all', [], {'': []}, [], False, True)
    self._split_help('./pants --help-all --help --help-advanced', [], {'': []}, [], True, True)
    self._split_help('./pants help --help-advanced', [], {'': []}, [], True, False)
    self._split_help('./pants help-advanced --help-all', [], {'': []}, [], True, True)
    self._split_help('./pants compile --help-advanced test', ['compile', 'test'],
                     {'': [], 'compile': [], 'test': []}, [], True, False)
    self._split_help('./pants help-advanced compile', ['compile'],
                     {'': [], 'compile': []}, [], True, False)
    self._split_help('./pants compile help-all test --help', ['compile', 'test'],
                     {'': [], 'compile': [], 'test': []}, [], False, True)

  def test_version_request_detection(self):
    self._split_version('./pants -V')
    self._split_version('./pants --version')

    # --version in a non-global scope is OK, and not a version request.
    self._split('./pants compile --version src/java/org/pantsbuild/foo',
                ['compile'],
                { '': [], 'compile': ['--version'], },
                ['src/java/org/pantsbuild/foo'])
