# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.help.build_dictionary_info_extracter import (BuildDictionaryInfoExtracter, FunctionArg,
                                                        TargetTypeInfo)


class BuildDictionaryInfoExtracterTest(unittest.TestCase):

  def test_get_description_from_docstring(self):
    class Test1(object):
      """First line.

      Subsequent lines.
      """

    self.assertEqual('First line.',
                     BuildDictionaryInfoExtracter.get_description_from_docstring(Test1))

    class Test2(object):
      """Only one line."""

    self.assertEqual('Only one line.',
                     BuildDictionaryInfoExtracter.get_description_from_docstring(Test2))

  def test_get_arg_descriptions_from_docstring(self):
    def func(a, b, c):
      """Foo function.

      :param a: Parameter a.
      :param  str  b: Parameter b.
      :param c:  Parameter c.
      """

    self.assertEqual({'a': 'Parameter a.', 'b': 'Parameter b.', 'c': 'Parameter c.'},
                     BuildDictionaryInfoExtracter.get_arg_descriptions_from_docstring(func))

  def test_get_function_args(self):
    # Test standalone function.
    def func(arg1, arg2, arg3=42, arg4=None, arg5='foo'):
      pass

    self.assertEqual([FunctionArg('arg1', '', False, None), FunctionArg('arg2', '', False, None),
                      FunctionArg('arg3', '', True, 42), FunctionArg('arg4', '', True, None),
                      FunctionArg('arg5', '', True, 'foo')],
      BuildDictionaryInfoExtracter.get_function_args(func))

    # Test member function.
    class TestCls(object):
      def __init__(self, arg1, arg2=False):
        pass

    self.assertEqual([FunctionArg('arg1', '', False, None), FunctionArg('arg2', '', True, False)],
                     BuildDictionaryInfoExtracter.get_function_args(TestCls.__init__))

  def test_get_target_args(self):
    class Target1(Target):
      def __init__(self, arg1, arg2=42, **kwargs):
        """
        :param arg1: The first arg.
        :param arg2: The second arg.
        """
        super(Target1, self).__init__(**kwargs)

    class Target2(Target1):
      pass

    class Target3(Target2):
      def __init__(self, arg3, arg4=None, **kwargs):
        super(Target1, self).__init__(**kwargs)

    self.maxDiff = None
    self.assertEqual(BuildDictionaryInfoExtracter.basic_target_args + [
                       FunctionArg('arg1', 'The first arg.', False, None),
                       FunctionArg('arg2', 'The second arg.', True, 42),
                       FunctionArg('arg3', '', False, None),
                       FunctionArg('arg4', '', True, None)
                     ],
                     BuildDictionaryInfoExtracter.get_target_args(Target3))

  def test_get_target_type_info(self):
    class Target1(Target):
      """Target1 docstring."""
      pass

    class Target2a(Target):
      # No docstring, so we should take the onefrom Target2b.
      pass

    class Target2b(Target):
      """Target2 docstring."""
      pass

    class Target3(Target):
      """Target3 docstring."""
      pass

    # We shouldn't get as far as invoking the context factory, so it can be trivial.
    macro_factory = TargetMacro.Factory.wrap(lambda ctx: None, Target2a, Target2b)

    bfa = BuildFileAliases(targets={
        'target1': Target1,
        'target2': macro_factory,
        'target3': Target3,
      },
      objects={},
      context_aware_object_factories={}
    )

    extracter = BuildDictionaryInfoExtracter(bfa)
    self.assertEquals([TargetTypeInfo('target1', 'Target1 docstring.'),
                       TargetTypeInfo('target2', 'Target2 docstring.'),
                       TargetTypeInfo('target3', 'Target3 docstring.')],
                      extracter.get_target_type_info())
