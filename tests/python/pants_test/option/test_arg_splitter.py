# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import shlex
import unittest

from pants.option.arg_splitter import (ArgSplitter, NoGoalHelp, OptionsHelp, UnknownGoalHelp,
                                       VersionHelp)
from pants.option.scope import ScopeInfo


def task(scope):
  return ScopeInfo(scope, ScopeInfo.TASK)


def intermediate(scope):
  return ScopeInfo(scope, ScopeInfo.INTERMEDIATE)


def subsys(scope):
  return ScopeInfo(scope, ScopeInfo.SUBSYSTEM)


class ArgSplitterTest(unittest.TestCase):
  _known_scope_infos = [intermediate('compile'), task('compile.java'), task('compile.scala'),
                        subsys('jvm'), subsys('jvm.test.junit'),
                        subsys('reporting'), intermediate('test'), task('test.junit')]

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
                      (isinstance(splitter.help_request, OptionsHelp) and
                       splitter.help_request.advanced))
    self.assertEquals(expected_help_all,
                      (isinstance(splitter.help_request, OptionsHelp) and
                       splitter.help_request.all_scopes))

  def _split_help(self, args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
                  expected_help_advanced=False, expected_help_all=False):
    self._split(args_str, expected_goals, expected_scope_to_flags, expected_target_specs,
                expected_passthru=None, expected_passthru_owner=None,
                expected_is_help=True,
                expected_help_advanced=expected_help_advanced,
                expected_help_all=expected_help_all)

  def _split_version_request(self, args_str):
    splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
    splitter.split_args(shlex.split(args_str))
    self.assertTrue(isinstance(splitter.help_request, VersionHelp))

  def _split_unknown_goal(self, args_str, unknown_goals):
    splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
    splitter.split_args(shlex.split(args_str))
    self.assertTrue(isinstance(splitter.help_request, UnknownGoalHelp))
    self.assertSetEqual(set(unknown_goals), set(splitter.help_request.unknown_goals))

  def _split_no_goal(self, args_str):
    splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
    splitter.split_args(shlex.split(args_str))
    self.assertTrue(isinstance(splitter.help_request, NoGoalHelp))

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
    self._split('./pants compile test --compile-java-bar --no-test-junit-baz foo/bar',
                ['compile', 'test'],
                {'': [], 'compile': [], 'compile.java': ['--bar'], 'test': [],
                 'test.junit': ['--no-baz']}, ['foo/bar'])

    # Qualified flags don't count as explicit goals.
    self._split('./pants compile --test-junit-bar foo/bar',
                ['compile'],
                {'': [], 'compile': [], 'test.junit': ['--bar']}, ['foo/bar'])

  def test_passthru_args(self):
    self._split('./pants test foo/bar -- -t arg',
                ['test'],
                {'': [], 'test': []},
                ['foo/bar'],
                expected_passthru=['-t', 'arg'],
                expected_passthru_owner='test')
    self._split('./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii '
                '--compile-java-long-flag src/java/org/pantsbuild/foo '
                'src/java/org/pantsbuild/bar:baz '
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
    self._split('./pants --jvm-options=-Dbar=baz test foo:bar',
                ['test'],
                {'': [], 'jvm': ['--options=-Dbar=baz'], 'test': []}, ['foo:bar'])
    # Qualified task subsystem flag in global scope.
    self._split('./pants --jvm-test-junit-options=-Dbar=baz test foo:bar',
                ['test'],
                {'': [], 'jvm.test.junit': ['--options=-Dbar=baz'], 'test': []}, ['foo:bar'])
    # Unqualified task subsystem flag in task scope.
    # Note that this exposes a small problem: You can't set an option on the cmd-line if that
    # option's name begins with any subsystem scope. For example, if test.junit has some option
    # named --jvm-foo, then it cannot be set on the cmd-line, because the ArgSplitter will assume
    # it's an option --foo on the jvm subsystem.
    self._split('./pants test.junit --jvm-options=-Dbar=baz foo:bar',
                ['test'],
                {'': [], 'jvm.test.junit': ['--options=-Dbar=baz'], 'test.junit': []}, ['foo:bar'])
    # Global-only flag in task scope.
    self._split('./pants test.junit --reporting-template-dir=path foo:bar',
                ['test'],
                {'': [], 'reporting': ['--template-dir=path'], 'test.junit': []}, ['foo:bar'])

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
    self._split_version_request('./pants -v')
    self._split_version_request('./pants -V')
    self._split_version_request('./pants --version')
    # A version request supercedes anything else.
    self._split_version_request('./pants --version compile --foo --bar path/to/target')

  def test_unknown_goal_detection(self):
    self._split_unknown_goal('./pants foo', ['foo'])
    self._split_unknown_goal('./pants compile foo', ['foo'])
    self._split_unknown_goal('./pants foo bar baz:qux', ['foo', 'bar'])
    self._split_unknown_goal('./pants foo compile bar baz:qux', ['foo', 'bar'])

  def test_no_goal_detection(self):
    self._split_no_goal('./pants foo/bar:baz')
