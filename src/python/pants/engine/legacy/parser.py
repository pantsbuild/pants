# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading

import six

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.parse_context import ParseContext
from pants.engine.legacy.structs import BundleAdaptor, Globs, RGlobs, TargetAdaptor, ZGlobs
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

  _objects = []
  _lock = threading.Lock()

  @classmethod
  @memoized_method
  def _get_symbols(cls, symbol_table_cls):
    symbol_table = symbol_table_cls.table()
    # TODO: Nasty escape hatch: see https://github.com/pantsbuild/pants/issues/3561
    aliases = symbol_table_cls.aliases()

    class Registrar(BuildFileTargetFactory):
      def __init__(self, type_alias, object_type):
        self._type_alias = type_alias
        self._object_type = object_type
        self._serializable = Serializable.is_serializable_type(self._object_type)

      @memoized_property
      def target_types(self):
        return [self._object_type]

      def __call__(self, *args, **kwargs):
        name = kwargs.get('name')
        if name and self._serializable:
          kwargs.setdefault('type_alias', self._type_alias)
          obj = self._object_type(**kwargs)
          cls._objects.append(obj)
          return obj
        else:
          return self._object_type(*args, **kwargs)

    symbols = {}

    for alias, symbol in symbol_table.items():
      registrar = Registrar(alias, symbol)
      symbols[alias] = registrar
      symbols[symbol] = registrar

    if aliases.objects:
      symbols.update(aliases.objects)

    # Compute "per path" symbols (which will all use the same mutable ParseContext).
    # TODO: See https://github.com/pantsbuild/pants/issues/3561
    parse_context = ParseContext(rel_path='', type_aliases=symbols)
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
    symbols['globs'] = Globs
    symbols['rglobs'] = RGlobs
    symbols['zglobs'] = ZGlobs
    symbols['bundle'] = BundleAdaptor

    return symbols, parse_context

  @classmethod
  def parse(cls, filepath, filecontent, symbol_table_cls):
    symbols, parse_context = cls._get_symbols(symbol_table_cls)
    python = filecontent

    # Mutate the parse context for the new path.
    parse_context._rel_path = os.path.dirname(filepath)

    with cls._lock:
      del cls._objects[:]
      six.exec_(python, symbols)
      return list(cls._objects)
