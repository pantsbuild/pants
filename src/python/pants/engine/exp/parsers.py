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

from pants.build_graph.address import Address
from pants.engine.exp.objects import Resolvable, Serializable
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


def _read(path):
  try:
    with open(path) as fp:
      return fp.read()
  except OSError as e:
    raise ParseError('Problem reading path {}: {}'.format(path, e))


def _object_decoder(obj, symbol_table):
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


def parse_json(path, symbol_table=None):
  """Parse the given json encoded string into a list of top-level objects found.

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
  json = _read(path)

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

      raise ParseError('{error}\nIn document at {path}:\n{json_data}'
                       .format(error=e,
                               path=path,
                               json_data='\n'.join(header_lines + formatted_json_lines)))

  return objects


def _object_encoder(obj, inline):
  if isinstance(obj, Resolvable):
    return obj.resolve() if inline else obj.address
  if isinstance(obj, Address):
    return obj.reference()
  if not Serializable.is_serializable(obj):
    raise ParseError('Can only encode Serializable objects in JSON, given {!r} of type {}'
                     .format(obj, type(obj).__name__))

  encoded = obj._asdict()
  if 'type_alias' not in encoded:
    encoded = encoded.copy()
    encoded['type_alias'] = '{}.{}'.format(inspect.getmodule(obj).__name__, type(obj).__name__)
  return {k: v for k, v in encoded.items() if v}


def encode_json(obj, inline=False, **kwargs):
  """Encode the given object as json.

  Supports objects that follow the `_asdict` protocol.  See `parse_json` for more information.

  :param obj: A serializable object.
  :param bool inline: `True` to inline all resolvable objects as nested JSON objects, `False` to
                      serialize those objects' addresses instead; `False` by default.
  :param **kwargs: Any kwargs accepted by :class:`json.JSONEncoder` besides `encoding` and
                   `default`.
  :returns: A UTF-8 json encoded blob representing the object.
  :rtype: string
  :raises: :class:`ParseError` if there were any problems encoding the given `obj` in json.
  """
  encoder = JSONEncoder(encoding='UTF-8',
                        default=functools.partial(_object_encoder, inline=inline),
                        **kwargs)
  return encoder.encode(obj)


def python_assignments_parser(symbol_table=None):
  """Return a parser that parses the given python code into a list of top-level objects found.

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
    python = _read(path)
    symbols = {}
    six.exec_(python, parse_globals, symbols)

    objects = []
    for name, obj in symbols.items():
      if isinstance(obj, type):
        # Allow type imports
        continue

      if not Serializable.is_serializable(obj):
        raise ParseError('Found a non-serializable top-level object: {}'.format(obj))

      attributes = obj._asdict()
      if 'name' in attributes:
        attributes = attributes.copy()
        redundant_name = attributes.pop('name', None)
        if redundant_name and redundant_name != name:
          raise ParseError('The object named {!r} is assigned to a mismatching name {!r}'
                           .format(redundant_name, name))
      obj_type = type(obj)
      named_obj = obj_type(name=name, **attributes)
      objects.append(named_obj)
    return objects

  return parse


def python_callbacks_parser(symbol_table):
  """Return a parser that parses the given python code into a list of top-level objects found.

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  :param dict symbol_table: The symbol table to expose to the python file being parsed.
  :returns: A callable that accepts a string path and returns a list of decoded addressable,
            Serializable objects.  The callable will raise :class:`ParseError` if there were any
            problems encountered parsing the python BUILD file at the given path.
  :rtype: :class:`collections.Callable`
  """
  objects = []

  def registered(type_name, object_type, name=None, **kwargs):
    if name:
      obj = object_type(name=name, type_alias=type_name, **kwargs)
      if Serializable.is_serializable(obj):
        objects.append(obj)
      return obj
    else:
      return object_type(type_alias=type_name, **kwargs)

  parse_globals = {}
  for alias, symbol in symbol_table.items():
    parse_globals[alias] = functools.partial(registered, alias, symbol)

  lock = threading.Lock()

  def parse(path):
    python = _read(path)
    with lock:
      del objects[:]
      six.exec_(python, parse_globals, {})
      return list(objects)

  return parse
