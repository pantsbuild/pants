# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import importlib
import inspect
from json.decoder import JSONDecoder
from json.encoder import JSONEncoder

import six

from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized


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
  typename = obj.get('typename', None)
  if not typename:
    return obj
  else:
    symbol = symbol_table(typename)
    return symbol(**obj)


@memoized(key_factory=lambda t: tuple(sorted(t.items())) if t is not None else None)
def _get_decoder(symbol_table=None):
  return functools.partial(_object_decoder,
                           symbol_table=symbol_table.__getitem__ if symbol_table else _as_type)


def _object_encoder(o):
  if not Serializable.is_serializable(o):
    raise ParseError('Can only encode Serializable objects in JSON, given {!r} of type {}'
                     .format(o, type(o).__name__))
  encoded = o._asdict()
  if 'typename' not in encoded:
    encoded['typename'] = '{}.{}'.format(inspect.getmodule(o).__name__, type(o).__name__)
  return encoded


encoder = JSONEncoder(encoding='UTF-8', default=_object_encoder, sort_keys=True, indent=True)


def parse_json(json, symbol_table=None):
  """Parses the given json encoded string into a list of top-level objects found.

  The parser accepts both blank lines and comment lines (those beginning with optional whitespace
  followed by the '#' character) as well as more than one top-level JSON object.

  The parse also supports a simple protocol for serialized types that have an `_asdict` method.
  This includes `namedtuple` subtypes as well as any custom class with an `_asdict` method defined;
  see :class:`pants.engine.exp.serializable.Serializable`.

  :param string json: A json encoded document with extra support for blank lines, comments and
                      multiple top-level objects.
  :returns: A list of decoded json data.
  :rtype: list
  :raises: :class:`ParseError` if there were any problems encountered parsing the given `json`.
  """

  decoder = JSONDecoder(encoding='UTF-8', object_hook=_get_decoder(symbol_table), strict=True)

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
  # TODO(John Sirois): Support an alias map from type (or from fqcn) -> typename.
  return encoder.encode(obj)


def parse_python_assignments(python, symbol_table=None):
  """Parses the given python code into a list of top-level addressable Serializable objects found.

  Only Serializable objects assigned to top-level variables will be collected and returned.  These
  objects will be addressable via their top-level variable names in the parsed namespace.

  :param string python: A python build file blob.
  :returns: A list of decoded addressable, Serializable objects.
  :rtype: list
  :raises: :class:`ParseError` if there were any problems encountered parsing the given `python`.
  """
  def aliased(type_name, object_type, **kwargs):
    return object_type(typename=type_name, **kwargs)

  parse_globals = {}
  for alias, symbol in (symbol_table or {}).items():
    parse_globals[alias] = functools.partial(aliased, alias, symbol)

  symbols = {}
  six.exec_(python, parse_globals, symbols)
  objects = []
  for name, obj in symbols.items():
    if Serializable.is_serializable(obj):
      attributes = obj._asdict()
      redundant_name = attributes.pop('name', name)
      if redundant_name and redundant_name != name:
        raise ParseError('The object named {!r} is assigned to a mismatching name {!r}'
                         .format(redundant_name, name))
      obj_type = type(obj)
      named_obj = obj_type(name=name, **attributes)
      objects.append(named_obj)
  return objects


def parse_python_callbacks(python, symbol_table):
  """Parses the given python code into a list of top-level addressable Serializable objects found.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  :param string python: A python build file blob.
  :returns: A list of decoded addressable, Serializable objects.
  :rtype: list
  :raises: :class:`ParseError` if there were any problems encountered parsing the given `python`.
  """
  objects = []

  def registered(type_name, object_type, name=None, **kwargs):
    if name:
      obj = object_type(name=name, typename=type_name, **kwargs)
      if Serializable.is_serializable(obj):
        objects.append(obj)
      return obj
    else:
      return object_type(typename=type_name, **kwargs)

  parse_globals = {}
  for alias, symbol in symbol_table.items():
    parse_globals[alias] = functools.partial(registered, alias, symbol)
  six.exec_(python, parse_globals, {})
  return objects
