# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import importlib
import inspect
import threading
from json.decoder import JSONDecoder
from json.encoder import JSONEncoder

import six

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized, memoized_property


@memoized
def _import(typename):
  modulename, _, symbolname = typename.rpartition('.')
  if not modulename:
    raise ParseError('Expected a fully qualified type name, given {}'.format(typename))
  try:
    mod = importlib.import_module(modulename)
    try:
      return getattr(mod, symbolname)
    except AttributeError:
      raise ParseError('The symbol {} was not found in module {} when attempting to convert '
                       'type name {}'.format(symbolname, modulename, typename))
  except ImportError as e:
    raise ParseError('Failed to import type name {} from module {}: {}'
                     .format(typename, modulename, e))


def _as_type(type_or_name):
  return _import(type_or_name) if isinstance(type_or_name, six.string_types) else type_or_name


class ParseError(Exception):
  """Indicates an error parsing BUILD configuration."""


def _object_decoder(obj, symbol_table=None):
  # A magic field will indicate type and this can be used to wrap the object in a type.
  type_alias = obj.get('type_alias', None)
  if not type_alias:
    return obj
  else:
    symbol = symbol_table(type_alias)
    return symbol(**obj)


@memoized(key_factory=lambda t: tuple(sorted(t.items())) if t is not None else None)
def _get_decoder(symbol_table=None):
  decoder = functools.partial(_object_decoder,
                              symbol_table=symbol_table.__getitem__ if symbol_table else _as_type)
  return JSONDecoder(encoding='UTF-8', object_hook=decoder, strict=True)


def _object_encoder(o):
  if not Serializable.is_serializable(o):
    raise ParseError('Can only encode Serializable objects in JSON, given {!r} of type {}'
                     .format(o, type(o).__name__))
  encoded = o._asdict()
  if 'type_alias' not in encoded:
    encoded = encoded.copy()
    encoded['type_alias'] = '{}.{}'.format(inspect.getmodule(o).__name__, type(o).__name__)
  return encoded


encoder = JSONEncoder(encoding='UTF-8', default=_object_encoder, sort_keys=True, indent=True)


def parse_json(path, symbol_table=None):
  """Parses the given json encoded string into a list of top-level objects found.

  The parser accepts both blank lines and comment lines (those beginning with optional whitespace
  followed by the '#' character) as well as more than one top-level JSON object.

  The parse also supports a simple protocol for serialized types that have an `_asdict` method.
  This includes `namedtuple` subtypes as well as any custom class with an `_asdict` method defined;
  see :class:`pants.engine.exp.serializable.Serializable`.

  :param string path: The path of a json encoded document with extra support for blank lines,
                      comments and multiple top-level objects.
  :returns: A list of decoded json data.
  :rtype: list
  :raises: :class:`ParseError` if there were any problems encountered parsing the given `json`.
  """
  with open(path) as fp:
    json = fp.read()

  decoder = _get_decoder(symbol_table)

  # Strip comment lines and blank lines, which we allow, but preserve enough information about the
  # stripping to constitute a reasonable error message that can be used to find the portion of the
  # JSON document containing the error.

  def non_comment_line(l):
    stripped = l.lstrip()
    return stripped if (stripped and not stripped.startswith('#')) else None

  offset = 0
  objects = []
  while True:
    lines = json[offset:].splitlines()
    if not lines:
      break

    # Strip whitespace and comment lines preceding the next JSON object.
    while True:
      line = non_comment_line(lines[0])
      if not line:
        comment_line = lines.pop(0)
        offset += len(comment_line) + 1
      elif line.startswith('{') or line.startswith('['):
        # Account for leading space in this line that starts off the JSON object.
        offset += len(lines[0]) - len(line)
        break
      else:
        raise ParseError('Unexpected json line:\n{}'.format(lines[0]))

    lines = json[offset:].splitlines()
    if not lines:
      break

    # Prepare the JSON blob for parsing - strip blank and comment lines recording enough information
    # To reconstitute original offsets after the parse.
    comment_lines = []
    non_comment_lines = []
    for line_number, line in enumerate(lines):
      if non_comment_line(line):
        non_comment_lines.append(line)
      else:
        comment_lines.append((line_number, line))

    data = '\n'.join(non_comment_lines)
    try:
      obj, idx = decoder.raw_decode(data)
      objects.append(obj)
      if idx >= len(data):
        break
      offset += idx

      # Add back in any parsed blank or comment line offsets.
      parsed_line_count = len(data[:idx].splitlines())
      for line_number, line in comment_lines:
        if line_number >= parsed_line_count:
          break
        offset += len(line) + 1
        parsed_line_count += 1
    except ValueError as e:
      json_lines = data.splitlines()
      col_width = len(str(len(json_lines)))

      col_padding = ' ' * col_width

      def format_line(line):
        return '{col_padding}  {line}'.format(col_padding=col_padding, line=line)

      header_lines = [format_line(line) for line in json[:offset].splitlines()]

      formatted_json_lines = [('{line_number:{col_width}}: {line}'
                               .format(col_width=col_width, line_number=line_number, line=line))
                              for line_number, line in enumerate(json_lines, start=1)]

      for line_number, line in comment_lines:
        formatted_json_lines.insert(line_number, format_line(line))

      raise ParseError('{error}\nIn document:\n{json_data}'
                       .format(error=e, json_data='\n'.join(header_lines + formatted_json_lines)))

  return objects


def encode_json(obj):
  """Encodes the given object as json.

  Supports objects that follow the `_asdict` protocol.  See `parse_json` for more information.

  :param obj: A serializable object.
  :returns: A json encoded blob representing the object.
  :rtype: string
  :raises: :class:`ParseError` if there were any problems encoding the given `obj` in json.
  """
  # TODO(John Sirois): Support an alias map from type (or from fqcn) -> type_alias.
  return encoder.encode(obj)


def python_assignments_parser(symbol_table=None):
  """Returns a parser that parses the given python code into a list of top-level objects found.

  Only Serializable objects assigned to top-level variables will be collected and returned.  These
  objects will be addressable via their top-level variable names in the parsed namespace.

  :param dict symbol_table: An optional symbol table to expose to the python file being parsed.
  :returns: A callable that accepts a string path and returns a list of decoded addressable,
            Serializable objects.  The callable will raise :class:`ParseError` if there were any
            problems encountered parsing the python BUILD file at the given path.
  :rtype: :class:`collections.Callable`
  """
  def aliased(type_alias, object_type, **kwargs):
    return object_type(type_alias=type_alias, **kwargs)

  parse_globals = {}
  for alias, symbol in (symbol_table or {}).items():
    parse_globals[alias] = functools.partial(aliased, alias, symbol)

  def parse(path):
    symbols = {}
    with open(path) as fp:
      six.exec_(fp.read(), parse_globals, symbols)

    objects = []
    for name, obj in symbols.items():
      if isinstance(obj, type):
        # Allow type imports
        continue

      if not Serializable.is_serializable(obj):
        raise ParseError('Found a non-serializable top-level object: {}'.format(obj))

      attributes = obj._asdict().copy()
      redundant_name = attributes.pop('name', None)
      if redundant_name and redundant_name != name:
        raise ParseError('The object named {!r} is assigned to a mismatching name {!r}'
                         .format(redundant_name, name))
      obj_type = type(obj)
      named_obj = obj_type(name=name, **attributes)
      objects.append(named_obj)
    return objects

  return parse


def python_callbacks_parser(symbol_table, object_table=None, per_path_symbol_factory=None):
  """Returns a parser that parses the given python code into a list of top-level objects.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

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
