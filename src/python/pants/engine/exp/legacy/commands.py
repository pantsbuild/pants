# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.parse_context import ParseContext
from pants.bin.goal_runner import OptionsInitializer
from pants.engine.exp.legacy.parsers import legacy_python_callbacks_parser
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.targets import Target


def list():
  """Lists all addresses under the current build root subject to `--spec-excludes` constraints."""
  build_root = get_buildroot()

  options, build_config = OptionsInitializer().setup()
  aliases = build_config.registered_aliases()

  symbol_table = {alias: Target for alias in aliases.target_types}

  object_table = aliases.objects

  def per_path_symbol_factory(path, global_symbols):
    per_path_symbols = {}

    symbols = global_symbols.copy()
    for alias, target_macro_factory in aliases.target_macro_factories.items():
      for target_type in target_macro_factory.target_types:
        symbols[target_type] = lambda *args, **kwargs: per_path_symbols[alias](*args, **kwargs)

    parse_context = ParseContext(rel_path=os.path.relpath(os.path.dirname(path), build_root),
                                 type_aliases=symbols)

    for alias, object_factory in aliases.context_aware_object_factories.items():
      per_path_symbols[alias] = object_factory(parse_context)

    for alias, target_macro_factory in aliases.target_macro_factories.items():
      target_macro = target_macro_factory.target_macro(parse_context)
      per_path_symbols[alias] = target_macro
      for target_type in target_macro_factory.target_types:
        per_path_symbols[target_type] = target_macro

    return per_path_symbols

  parser = legacy_python_callbacks_parser(symbol_table,
                                          object_table=object_table,
                                          per_path_symbol_factory=per_path_symbol_factory)
  mapper = AddressMapper(build_root, parser=parser)

  spec_excludes = options.for_global_scope().spec_excludes
  for address, obj in mapper.walk_addressables(path_excludes=spec_excludes):
    print(address.spec)
