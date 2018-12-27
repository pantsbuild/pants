# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os

from future.utils import text_type

from pants.engine.fs import FileContent
from pants.engine.legacy.parser import AbstractLegacyPythonCallbacksParser
from pants.util.objects import datatype, Collection

logger = logging.getLogger(__name__)


class Call(datatype([
  ("function_name", text_type),
  ("args", tuple),
  ("kwargs", tuple),
])):
  """Represents a call to a python function mirrored into starlark."""


class CallIndex(datatype([("i", int)])):
  """A pointer into a list of Calls."""


ParseOutput = Collection.of(Call)


class ParseInput(datatype([
  ("file_content", FileContent),
  ("function_names", tuple)
])):
  """The input to a starlark parse."""


class ParseFunction(datatype([
  ("function_name", text_type),
])):
  """A reference to a function (the index into the symbols dict)."""


class StarlarkParser(AbstractLegacyPythonCallbacksParser):
  """A parser that parses the given python code into a list of top-level via s starlark interpreter..

  Only Serializable objects with `name`s will be collected and returned.  These objects will be
  addressable via their name in the parsed namespace.

  This parser attempts to be compatible with existing legacy BUILD files and concepts including
  macros and target factories.
  """

  def __init__(self, symbol_table, aliases, build_file_imports_behavior):
    """
    :param symbol_table: A SymbolTable for this parser, which will be overlaid with the given
      additional aliases.
    :type symbol_table: :class:`pants.engine.parser.SymbolTable`
    :param aliases: Additional BuildFileAliases to register.
    :type aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`
    :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
      import statements. Valid values: "allow", "warn", "error". Must be "error".
    :type build_file_imports_behavior: string
    """
    super(StarlarkParser, self).__init__(symbol_table, aliases)
    if build_file_imports_behavior != "error":
      raise ValueError(
        "Starlark parse doesn't support imports; --build-file-imports must be error but was {}".format(
          build_file_imports_behavior
        )
      )


  def parse(self, filepath, filecontent, parsed_objects):
    # Mutate the parse context for the new path, then exec, and copy the resulting objects.
    # We execute with a (shallow) clone of the symbols as a defense against accidental
    # pollution of the namespace via imports or variable definitions. Defending against
    # _intentional_ mutation would require a deep clone, which doesn't seem worth the cost at
    # this juncture.
    self._parse_context._storage.clear(os.path.dirname(filepath))
    for obj in parsed_objects:
      self.evaluate(obj, parsed_objects, self._symbols)
    return list(self._parse_context._storage.objects)


  def evaluate(self, v, parsed_objects, symbols):
    if isinstance(v, Call):
      kwargs = ({k: self.evaluate(v, parsed_objects, symbols) for k, v in v.kwargs})
      args = [self.evaluate(arg, parsed_objects, symbols) for arg in v.args]
      func = symbols[v.function_name]
      return func(*args, **kwargs)
    elif isinstance(v, CallIndex):
      return self.evaluate(parsed_objects.dependencies[v.i], parsed_objects, symbols)
    elif isinstance(v, ParseFunction):
      return symbols[v.function_name]
    elif isinstance(v, tuple):
      return [self.evaluate(item, parsed_objects, symbols) for item in v]
    else:
      return v
