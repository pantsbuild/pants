# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading

import six

from pants.base.build_environment import get_buildroot
from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.parse_context import ParseContext
from pants.engine.exp.objects import Serializable
from pants.engine.exp.parsers import Parser
from pants.engine.exp.targets import Target
from pants.util.memo import memoized_method, memoized_property


class LegacyPythonCallbacksParser(Parser):
  """A parser that parses the given python code into a list of top-level objects.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  This parser attempts to be compatible with existing legacy BUILD files and concepts including
  macros and target factories.

  :param dict object_table: An optional symbol table of plain python objects to expose.  This is
                            intended to support compatibility with the legacy parsing system and
                            its exposed objects.
  :param per_path_symbol_factory: An optional factory for any symbols needing the current path;
                                  called with (path, global_symbols), should return a dict of
                                  per-path symbols.  This is intended to support compatibility with
                                  the legacy parsing system and context aware symbols.
  :type per_path_symbol_factory: :class:`collections.Callable`
  :returns: A callable that accepts a string path and returns a list of decoded addressable,
            Serializable objects.  The callable will raise :class:`ParseError` if there were any
            problems encountered parsing the python BUILD file at the given path.
  :rtype: :class:`collections.Callable`
  """

  _objects = []
  _lock = threading.Lock()

  @classmethod
  def _per_path_symbol_factory(cls, build_root, path, aliases, global_symbols):
    per_path_symbols = {}

    symbols = global_symbols.copy()
    for alias, target_macro_factory in aliases.target_macro_factories.items():
      for target_type in target_macro_factory.target_types:
        symbols[target_type] = Target

    parse_context = ParseContext(rel_path=os.path.relpath(os.path.dirname(path), build_root),
                                 type_aliases=symbols)

    for alias, object_factory in aliases.context_aware_object_factories.items():
      per_path_symbols[alias] = object_factory(parse_context)

    for alias, target_macro_factory in aliases.target_macro_factories.items():
      target_macro = target_macro_factory.target_macro(parse_context)
      per_path_symbols[alias] = target_macro
      for target_type in target_macro_factory.target_types:
        per_path_symbols[target_type] = Target

    return per_path_symbols

  @classmethod
  @memoized_method
  def _get_globals(cls, symbol_table_cls):
    build_root = get_buildroot()

    symbol_table = symbol_table_cls.table()
    # TODO: nasty escape hatch
    object_table = symbol_table_cls.aliases().objects

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
          obj = self._object_type(type_alias=self._type_alias, **kwargs)
          cls._objects.append(obj)
          return obj
        else:
          return self._object_type(*args, **kwargs)

    parse_globals = {}
    for alias, symbol in symbol_table.items():
      registrar = Registrar(alias, symbol)
      parse_globals[alias] = registrar
      parse_globals[symbol] = registrar

    if object_table:
      parse_globals.update(object_table)
    return build_root, parse_globals

  @classmethod
  def parse(cls, path, symbol_table_cls):
    build_root, parse_globals = cls._get_globals(symbol_table_cls)
    with open(path) as fp:
      python = fp.read()

    symbols = cls._per_path_symbol_factory(build_root,
                                           path,
                                           symbol_table_cls.aliases(),
                                           parse_globals)
    symbols.update(parse_globals)

    with cls._lock:
      del cls._objects[:]
      six.exec_(python, symbols, {})
      return list(cls._objects)
