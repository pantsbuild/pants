# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import tokenize
from io import StringIO
from typing import Dict, Tuple

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.exceptions import UnaddressableObjectError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.legacy.structs import BundleAdaptor, TargetAdaptor
from pants.engine.objects import Serializable
from pants.engine.parser import ParseError, Parser, SymbolTable
from pants.option.global_options import BuildFileImportsBehavior
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)


class LegacyPythonCallbacksParser(Parser):
    """A parser that parses the given python code into a list of top-level objects.

    Only Serializable objects with `name`s will be collected and returned.  These objects will be
    addressable via their name in the parsed namespace.

    This parser attempts to be compatible with existing legacy BUILD files and concepts including
    macros and target factories.
    """

    def __init__(
        self,
        symbol_table: SymbolTable,
        aliases: BuildFileAliases,
        build_file_imports_behavior: BuildFileImportsBehavior,
    ) -> None:
        """
        :param symbol_table: A SymbolTable for this parser, which will be overlaid with the given
          additional aliases.
        :param aliases: Additional BuildFileAliases to register.
        :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
          import statements.
        """
        super().__init__()
        self._symbols, self._parse_context = self._generate_symbols(symbol_table, aliases)
        self._build_file_imports_behavior = build_file_imports_behavior

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

    def parse(self, filepath: str, filecontent: bytes):
        python = filecontent.decode()

        # Mutate the parse context for the new path, then exec, and copy the resulting objects.
        # We execute with a (shallow) clone of the symbols as a defense against accidental
        # pollution of the namespace via imports or variable definitions. Defending against
        # _intentional_ mutation would require a deep clone, which doesn't seem worth the cost at
        # this juncture.
        self._parse_context._storage.clear(os.path.dirname(filepath))
        exec(python, dict(self._symbols))

        # Perform this check after successful execution, so we know the python is valid (and should
        # tokenize properly!)
        # Note that this is incredibly poor sandboxing. There are many ways to get around it.
        # But it's sufficient to tell most users who aren't being actively malicious that they're doing
        # something wrong, and it has a low performance overhead.
        if "import" in python:
            io_wrapped_python = StringIO(python)
            for token in tokenize.generate_tokens(io_wrapped_python.readline):
                token_str = token[1]
                lineno, _ = token[2]

                if token_str != "import":
                    continue

                if self._build_file_imports_behavior == BuildFileImportsBehavior.warn:
                    logger.warning(
                        f"Import used in {filepath} at line {lineno}. Import statements should "
                        f"be avoided in BUILD files because they can easily break Pants caching and lead to "
                        f"stale results. Instead, consider rewriting your code into a Pants plugin: "
                        f"https://www.pantsbuild.org/howto_plugin.html"
                    )
                else:
                    raise ParseError(
                        f"Import used in {filepath} at line {lineno}. Import statements are banned in "
                        f"BUILD files in this repository and should generally be avoided because "
                        f"they can easily break Pants caching and lead to stale results. Instead, consider "
                        f"rewriting your code into a Pants plugin: "
                        f"https://www.pantsbuild.org/howto_plugin.html"
                    )

        return list(self._parse_context._storage.objects)
