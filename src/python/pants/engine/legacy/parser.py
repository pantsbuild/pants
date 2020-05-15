# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from typing import Dict, Tuple

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.exceptions import UnaddressableObjectError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.build_files import error_on_imports
from pants.engine.internals.objects import Serializable
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, SymbolTable
from pants.engine.legacy.structs import BundleAdaptor, TargetAdaptor
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)


class LegacyPythonCallbacksParser(Parser):
    """A parser that parses the given python code into a list of top-level objects.

    Only Serializable objects with `name`s will be collected and returned.  These objects will be
    addressable via their name in the parsed namespace.

    This parser attempts to be compatible with existing legacy BUILD files and concepts including
    macros and target factories.
    """

    def __init__(self, symbol_table: SymbolTable, aliases: BuildFileAliases) -> None:
        """
        :param symbol_table: A SymbolTable for this parser, which will be overlaid with the given
          additional aliases.
        :param aliases: Additional BuildFileAliases to register.
        """
        super().__init__()
        self._symbols, self._parse_context = self._generate_symbols(symbol_table, aliases)

    @staticmethod
    def _generate_symbols(
        symbol_table: SymbolTable, aliases: BuildFileAliases,
    ) -> Tuple[Dict, ParseContext]:
        symbols: Dict = {}

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
                if "name" not in kwargs and issubclass(self._object_type, TargetAdaptor):
                    dirname = os.path.basename(self._parse_context.rel_path)
                    if dirname:
                        kwargs["name"] = dirname
                    else:
                        raise UnaddressableObjectError(
                            "Targets in root-level BUILD files must be named explicitly."
                        )
                name = kwargs.get("name")
                if name and self._serializable:
                    kwargs.setdefault("type_alias", self._type_alias)
                    obj = self._object_type(**kwargs)
                    self._parse_context._storage.add(obj)
                    return obj
                else:
                    return self._object_type(*args, **kwargs)

        for alias, symbol in symbol_table.table.items():
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

        symbols["bundle"] = BundleAdaptor

        return symbols, parse_context

    def _make_symbols(self, extra_symbols: BuildFilePreludeSymbols):
        """Make a full dict of symbols to expose as globals to the BUILD file.

        This is subtle; functions have their own globals set on __globals__ which they derive from
        the environment where they were executed. So for each extra_symbol which comes from a
        separate execution environment, we need to to add all of our self._symbols to those
        __globals__, otherwise those extra symbols will not see our target aliases etc. This also
        means that if multiple prelude files are present, they probably cannot see each others'
        symbols. We may choose to change this at some point.
        """
        d = dict(self._symbols)
        for key, value in extra_symbols.symbols.items():
            if hasattr(value, "__globals__"):
                value.__globals__.update(d)
            d[key] = value
        return d

    def parse(self, filepath: str, filecontent: bytes, extra_symbols: BuildFilePreludeSymbols):
        python = filecontent.decode()

        # Mutate the parse context for the new path, then exec, and copy the resulting objects.
        # We execute with a (shallow) clone of the symbols as a defense against accidental
        # pollution of the namespace via imports or variable definitions. Defending against
        # _intentional_ mutation would require a deep clone, which doesn't seem worth the cost at
        # this juncture.
        self._parse_context._storage.clear(os.path.dirname(filepath))
        exec(python, self._make_symbols(extra_symbols))

        error_on_imports(python, filepath)

        return list(self._parse_context._storage.objects)
