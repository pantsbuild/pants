# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import six

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.parse_context import ParseContext
from pants.engine.legacy.structs import BundleAdaptor, Globs, RGlobs, TargetAdaptor, ZGlobs
from pants.engine.mapper import UnaddressableObjectError
from pants.engine.objects import Serializable
from pants.engine.parser import Parser
from pants.util.memo import memoized_method, memoized_property


class LegacyPythonCallbacksParser(Parser):
  """A parser that parses the given python code into a list of top-level objects.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  This parser attempts to be compatible with existing legacy BUILD files and concepts including
  macros and target factories.
  """

  @classmethod
  @memoized_method
  def _get_symbols(cls, symbol_table_cls):
    symbol_table = symbol_table_cls.table()
    # TODO: Nasty escape hatch: see https://github.com/pantsbuild/pants/issues/3561
    aliases = symbol_table_cls.aliases()

    symbols = {}

    # Compute "per path" symbols.  For performance, we use the same ParseContext, which we
    # mutate (in a critical section) to set the rel_path appropriately before it's actually used.
    # This allows this memoized method to depend only on the symbol_table_cls, thus reusing
    # the same symbols for all parses.  Meanwhile we set the rel_path to None, so that we get
    # a loud error if anything tries to use it before it's set.
    # TODO: See https://github.com/pantsbuild/pants/issues/3561
    parse_context = ParseContext(rel_path=None, type_aliases=symbols)

    class Registrar(BuildFileTargetFactory):
      def __init__(self, type_alias, object_type):
        self._type_alias = type_alias
        self._object_type = object_type
        self._serializable = Serializable.is_serializable_type(self._object_type)

      @memoized_property
      def target_types(self):
        return [self._object_type]

      def __call__(self, *args, **kwargs):
        # Target names default to the name of the directory their BUILD file is in
        # (as long as it's not the root directory).
        if 'name' not in kwargs and issubclass(self._object_type, TargetAdaptor):
          dirname = os.path.basename(parse_context.rel_path)
          if dirname:
            kwargs['name'] = dirname
          else:
            raise UnaddressableObjectError(
                'Targets in root-level BUILD files must be named explicitly.')
        name = kwargs.get('name')
        if name and self._serializable:
          kwargs.setdefault('type_alias', self._type_alias)
          obj = self._object_type(**kwargs)
          parse_context._storage.add(obj)
          return obj
        else:
          return self._object_type(*args, **kwargs)

    for alias, symbol in symbol_table.items():
      registrar = Registrar(alias, symbol)
      symbols[alias] = registrar
      symbols[symbol] = registrar

    if aliases.objects:
      symbols.update(aliases.objects)

    for alias, object_factory in aliases.context_aware_object_factories.items():
      symbols[alias] = object_factory(parse_context)

    for alias, target_macro_factory in aliases.target_macro_factories.items():
      underlying_symbol = symbols.get(alias, TargetAdaptor)
      symbols[alias] = target_macro_factory.target_macro(parse_context)
      for target_type in target_macro_factory.target_types:
        symbols[target_type] = Registrar(alias, underlying_symbol)

    # TODO: Replace builtins for paths with objects that will create wrapped PathGlobs objects.
    # The strategy for https://github.com/pantsbuild/pants/issues/3560 should account for
    # migrating these additional captured arguments to typed Sources.
    def glob_wrapper(glob_type):
      def glob_factory(*args, **kwargs):
        return glob_type(*args, spec_path=parse_context.rel_path, **kwargs)
      return glob_factory
    symbols['globs'] = glob_wrapper(Globs)
    symbols['rglobs'] = glob_wrapper(RGlobs)
    symbols['zglobs'] = glob_wrapper(ZGlobs)

    symbols['bundle'] = BundleAdaptor

    return symbols, parse_context

  @classmethod
  def parse(cls, filepath, filecontent, symbol_table_cls):
    symbols, parse_context = cls._get_symbols(symbol_table_cls)
    python = filecontent

    # Mutate the parse context for the new path, then exec, and copy the resulting objects.
    parse_context._storage.clear(os.path.dirname(filepath))
    six.exec_(python, symbols)
    return list(parse_context._storage.objects)
