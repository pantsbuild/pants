# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading

import six

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized_property


def legacy_python_callbacks_parser(symbol_table, object_table=None, per_path_symbol_factory=None):
  """Return a parser that parses the given python code into a list of top-level objects.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  This parser attempts to be compatible with existing legacy BUILD files and concepts including
  macros and target factories.

  :param dict symbol_table: An optional symbol table to expose to the python file being parsed.
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
  objects = []

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
        objects.append(obj)
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

  lock = threading.Lock()

  def parse(path):
    with open(path) as fp:
      python = fp.read()

    if per_path_symbol_factory:
      symbols = per_path_symbol_factory(path, parse_globals)
      symbols.update(parse_globals)
    else:
      symbols = parse_globals

    with lock:
      del objects[:]
      six.exec_(python, symbols, {})
      return list(objects)

  return parse
