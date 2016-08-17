# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.help.build_dictionary_info_extracter import (BuildDictionaryInfoExtracter,
                                                        BuildSymbolInfo, FunctionArg)
from pants.util.objects import datatype


class BuildDictionaryInfoExtracterTest(unittest.TestCase):

  def setUp(self):
    super(BuildDictionaryInfoExtracterTest, self).setUp()
    self.maxDiff = None

  def test_get_description_from_docstring(self):
    class Test1(object):
      """First line.

      Subsequent
      lines.

        with indentations

      """

    self.assertEqual(('First line.', ['Subsequent', 'lines.', '', '  with indentations']),
                     BuildDictionaryInfoExtracter.get_description_from_docstring(Test1))

    class Test2(object):
      """Only one line."""

    self.assertEqual(('Only one line.', []),
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

  def test_get_multiline_arg_descriptions_from_docstring(self):
    # Test multiline parameter descriptions, including where all help is on subsequent line.
    def func(a, b, c, d, e):
      """Foo function.

      :param a: Parameter a.
      :param  str  b: Parameter b.
      :param c:  Parameter c
                 Second line Parameter c.
      :param d:
      Parameter d.
      :param e:  Parameter e.
      """

    self.assertEqual({'a': 'Parameter a.', 'b': 'Parameter b.',
                      'c': 'Parameter c Second line Parameter c.',
                      'd': 'Parameter d.', 'e': 'Parameter e.'},
                     BuildDictionaryInfoExtracter.get_arg_descriptions_from_docstring(func))

  def test_get_arg_descriptions_with_nonparams_from_docstring(self):
    # Test parameter help where help for items other than parameters is present.
    def func(a, b, c):
      """Foo function.

      :param a: Parameter a.
      :type j:  Type j.
      :type k:  Type k.
      Second line Type k.
      :param  str  b: Parameter b.
      :param c:  Parameter c.
      :returns:  Return.
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

    # Test *args, **kwargs situation.
    def generic_func(arg1, arg2=42, *args, **kwargs):
      """
      :param arg1: The first arg.
      :param arg2: The second arg.
      :param args: Some extra varargs.
      :param arg3: The third arg.
      :param arg4: The fourth arg (default: 'Foo').
      """

    self.assertEqual([FunctionArg('arg1', 'The first arg.', False, None),
                      FunctionArg('arg2', 'The second arg.', True, 42),
                      FunctionArg('*args', 'Some extra varargs.', False, None),
                      FunctionArg('arg3', 'The third arg.', True, None),
                      FunctionArg('arg4', "The fourth arg.", True, "'Foo'")],
                     BuildDictionaryInfoExtracter.get_function_args(generic_func))

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

    self.assertEqual(sorted(BuildDictionaryInfoExtracter.basic_target_args + [
                       FunctionArg('arg1', 'The first arg.', False, None),
                       FunctionArg('arg2', 'The second arg.', True, 42),
                       FunctionArg('arg3', '', False, None),
                       FunctionArg('arg4', '', True, None)
                     ]),
                     sorted(BuildDictionaryInfoExtracter.get_args_for_target_type(Target3)))

    # Check a trivial case.
    class Target4(Target):
      pass

    self.assertEqual(BuildDictionaryInfoExtracter.basic_target_args,
                     BuildDictionaryInfoExtracter.get_args_for_target_type(Target4))

  def test_get_target_type_info(self):
    class Target1(Target):
      """Target1 docstring."""
      pass

    class Target2a(Target):
      # No docstring, so we should take the one from Target2b.
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
    args = BuildDictionaryInfoExtracter.basic_target_args
    self.assertEquals([BuildSymbolInfo('target1', 'Target1 docstring.', [], args),
                       BuildSymbolInfo('target2', 'Target2 docstring.', [], args),
                       BuildSymbolInfo('target3', 'Target3 docstring.', [], args)],
                      extracter.get_target_type_info())

  def test_get_object_info(self):
    class Foo(object):
      """Foo docstring."""

      def __init__(self, bar, baz=42):
        """
        :param bar: Bar details.
        :param int baz: Baz details.
        """

    bfa = BuildFileAliases(targets={},
      objects={
        'foo': Foo
      },
      context_aware_object_factories={},
    )
    extracter = BuildDictionaryInfoExtracter(bfa)
    self.assertEquals([BuildSymbolInfo('foo', 'Foo docstring.', [],
                                       [FunctionArg('bar', 'Bar details.', False, None),
                                        FunctionArg('baz', 'Baz details.', True, 42)])],
                      extracter.get_object_info())

  def test_get_object_factory_info(self):
    class Foo(object):
      """Foo docstring."""

      def __call__(self, bar, baz=42):
        """
        :param bar: Bar details.
        :param int baz: Baz details.
        """

    bfa = BuildFileAliases(targets={},
      objects={},
      context_aware_object_factories={
        'foo': Foo
      }
    )
    extracter = BuildDictionaryInfoExtracter(bfa)
    self.assertEquals([BuildSymbolInfo('foo', 'Foo docstring.', [],
                                       [FunctionArg('bar', 'Bar details.', False, None),
                                        FunctionArg('baz', 'Baz details.', True, 42)])],
                      extracter.get_object_factory_info())

  def test_get_object_info_datatype(self):
    class FooDatatype(datatype('FooDatatype', ['bar', 'baz'])):
      """Foo docstring."""

      def __new__(cls, bar, baz=42):
        """
        :param bar: Bar details.
        :param int baz: Baz details.
        """
        return super(FooDatatype, cls).__new__(cls, bar, baz)

    bfa = BuildFileAliases(targets={},
      objects={
        'foo': FooDatatype
      },
      context_aware_object_factories={},
    )
    extracter = BuildDictionaryInfoExtracter(bfa)
    self.assertEquals([BuildSymbolInfo('foo', 'Foo docstring.', [],
                                       [FunctionArg('bar', 'Bar details.', False, None),
                                        FunctionArg('baz', 'Baz details.', True, 42)])],
                      extracter.get_object_info())
