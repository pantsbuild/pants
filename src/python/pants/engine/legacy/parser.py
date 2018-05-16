# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import tokenize
from StringIO import StringIO

import six

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.parse_context import ParseContext
from pants.engine.legacy.structs import BundleAdaptor, Globs, RGlobs, TargetAdaptor, ZGlobs
from pants.engine.mapper import UnaddressableObjectError
from pants.engine.objects import Serializable
from pants.engine.parser import ParseError, Parser
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class LegacyPythonCallbacksParser(Parser):
  """A parser that parses the given python code into a list of top-level objects.

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
      import statements. Valid values: "allow", "warn", "error".
    :type build_file_imports_behavior: string
    """
    super(LegacyPythonCallbacksParser, self).__init__()
    self._symbols, self._parse_context = self._generate_symbols(symbol_table, aliases)
    self._build_file_imports_behavior = build_file_imports_behavior

  @staticmethod
  def _generate_symbols(symbol_table, aliases):
    symbols = {}

    # Compute "per path" symbols.  For performance, we use the same ParseContext, which we
    # mutate (in a critical section) to set the rel_path appropriately before it's actually used.
    # This allows this method to reuse the same symbols for all parses.  Meanwhile we set the
    # rel_path to None, so that we get a loud error if anything tries to use it before it's set.
    # TODO: See https://github.com/pantsbuild/pants/issues/3561
    parse_context = ParseContext(rel_path=None, type_aliases=symbols)

    class Registrar(BuildFileTargetFactory):
      def __init__(self, parse_context, type_alias, object_type):
        self._parse_context = parse_context
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
          dirname = os.path.basename(self._parse_context.rel_path)
          if dirname:
            kwargs['name'] = dirname
          else:
            raise UnaddressableObjectError(
                'Targets in root-level BUILD files must be named explicitly.')
        name = kwargs.get('name')
        if name and self._serializable:
          kwargs.setdefault('type_alias', self._type_alias)
          obj = self._object_type(**kwargs)
          self._parse_context._storage.add(obj)
          return obj
        else:
          return self._object_type(*args, **kwargs)

    for alias, symbol in symbol_table.table().items():
      registrar = Registrar(parse_context, alias, symbol)
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
        symbols[target_type] = Registrar(parse_context, alias, underlying_symbol)

    # TODO: Replace builtins for paths with objects that will create wrapped PathGlobs objects.
    # The strategy for https://github.com/pantsbuild/pants/issues/3560 should account for
    # migrating these additional captured arguments to typed Sources.
    class GlobWrapper(object):
      def __init__(self, parse_context, glob_type):
        self._parse_context = parse_context
        self._glob_type = glob_type

      def __call__(self, *args, **kwargs):
        return self._glob_type(*args, spec_path=self._parse_context.rel_path, **kwargs)

    symbols['globs'] = GlobWrapper(parse_context, Globs)
    symbols['rglobs'] = GlobWrapper(parse_context, RGlobs)
    symbols['zglobs'] = GlobWrapper(parse_context, ZGlobs)

    symbols['bundle'] = BundleAdaptor

    return symbols, parse_context

  def parse(self, filepath, filecontent):
    python = filecontent

    # Mutate the parse context for the new path, then exec, and copy the resulting objects.
    # We execute with a (shallow) clone of the symbols as a defense against accidental
    # pollution of the namespace via imports or variable definitions. Defending against
    # _intentional_ mutation would require a deep clone, which doesn't seem worth the cost at
    # this juncture.
    self._parse_context._storage.clear(os.path.dirname(filepath))
    six.exec_(python, dict(self._symbols))

    # Perform this check after successful execution, so we know the python is valid (and should
    # tokenize properly!)
    # Note that this is incredibly poor sandboxing. There are many ways to get around it.
    # But it's sufficient to tell most users who aren't being actively malicious that they're doing
    # something wrong, and it has a low performance overhead.
    if self._build_file_imports_behavior != 'allow' and 'import' in python:
      for token in tokenize.generate_tokens(StringIO(python).readline):
        if token[1] == 'import':
          line_being_tokenized = token[4]
          if self._build_file_imports_behavior == 'warn':
            logger.warn('{} tried to import - import statements should be avoided ({})'.format(
              filepath,
              line_being_tokenized
            ))
          elif self._build_file_imports_behavior == 'error':
            raise ParseError(
              'import statements have been banned, but tried to import: {}'.format(
                line_being_tokenized
              )
            )
          else:
            raise ParseError(
              "Didn't know what to do for build_file_imports_behavior value {}".format(
                self._build_file_imports_behavior
              )
            )

    return list(self._parse_context._storage.objects)
