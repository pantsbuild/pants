# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import tokenize
from copy import copy
from io import StringIO
from pathlib import PurePath
from typing import Dict, Iterable, Tuple

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.deprecated import warn_or_error
from pants.base.exceptions import UnaddressableObjectError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.build_files import LoadStatementWithContent
from pants.engine.legacy.structs import BundleAdaptor, Globs, RGlobs, TargetAdaptor, ZGlobs
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

        # TODO: Replace builtins for paths with objects that will create wrapped PathGlobs objects.
        # The strategy for https://github.com/pantsbuild/pants/issues/3560 should account for
        # migrating these additional captured arguments to typed Sources.
        class GlobWrapper:
            def __init__(self, parse_context, glob_type):
                self._parse_context = parse_context
                self._glob_type = glob_type

            def __call__(self, *args, **kwargs):
                return self._glob_type(*args, spec_path=self._parse_context.rel_path, **kwargs)

        symbols["globs"] = GlobWrapper(parse_context, Globs)
        symbols["rglobs"] = GlobWrapper(parse_context, RGlobs)
        symbols["zglobs"] = GlobWrapper(parse_context, ZGlobs)

        symbols["bundle"] = BundleAdaptor

        # We need to handle loading seaparately, so we noop it at parse time.
        symbols["load"] = lambda *args: None

        return symbols, parse_context

    @staticmethod
    def check_for_deprecated_globs_usage(token: str, filepath: str, lineno: int) -> None:
        # We have this deprecation here, rather than in `engine/legacy/structs.py` where the
        # `sources` field is parsed, so that we can refer to the line number and filename as that
        # information is not passed to `structs.py`.
        if token in ["globs", "rglobs", "zglobs"]:
            script_instructions = (
                "curl -L -o fix_deprecated_globs_usage.py 'https://git.io/JvOKD' && chmod +x "
                "fix_deprecated_globs_usage.py && ./fix_deprecated_globs_usage.py "
                f"{PurePath(filepath).parent}"
            )
            warning = (
                f"Using deprecated `{token}` in {filepath} at line {lineno}. Instead, use a list "
                f"of files and globs, like `sources=['f1.py', '*.java']`. Specify excludes by putting "
                f"an `!` at the start of the value, like `!ignore.py`.\n\nWe recommend using our "
                f"migration script by running `{script_instructions}`"
            )
            warn_or_error(
                removal_version="1.27.0.dev0",
                deprecated_entity_description="Using `globs`, `rglobs`, and `zglobs`",
                hint=warning,
            )

    @staticmethod
    def _expose_symbols_from_loaded_files(
        load_statements: Iterable[LoadStatementWithContent], filepath: str
    ) -> Dict:
        """Expose symbols from loaded files.

        To achieve that, we exec() the contents of the imported file, which puts all defined symbols
        in `locals()`. We then copy `locals()` and filter it by the symbols the build file
        explicitly imports. `locals()` will be emptied at the end of each iteration of the outer
        `for` loop, so there is no chance of contamination.
        """
        extra_symbols: Dict = {}
        for statement in load_statements:
            content = statement.content.content.decode()
            symbols_to_expose = statement.symbols_to_expose
            exec(content)
            local_symbols = copy(
                locals()
            )  # We copy the locals so that they don't get lost in the for loop
            for symbol in symbols_to_expose:
                if symbol in local_symbols:
                    if symbol not in extra_symbols:
                        extra_symbols[symbol] = local_symbols[symbol]
                    else:
                        raise ParseError(
                            f"Trying to import symbol {symbol} from file {statement.path} into BUILD file {filepath}: ",
                            f"Which has already been loaded from another file.",
                        )
                else:
                    raise ParseError(
                        f"Trying to import symbol {symbol} from file {statement.path} into BUILD file {filepath}: ",
                        f"Symbol is not exported by loaded file.",
                    )
            logger.debug(
                f"Loaded symbols {symbols_to_expose} from {statement.path} into file {filepath}"
            )
        return extra_symbols

    def parse(
        self, filepath: str, filecontent: bytes, load_statements: Iterable[LoadStatementWithContent]
    ):
        python = filecontent.decode()

        # Mutate the parse context for the new path, then exec, and copy the resulting objects.
        # We execute with a (shallow) clone of the symbols as a defense against accidental
        # pollution of the namespace via imports or variable definitions. Defending against
        # _intentional_ mutation would require a deep clone, which doesn't seem worth the cost at
        # this juncture.
        self._parse_context._storage.clear(os.path.dirname(filepath))

        symbols_loaded_from_files = LegacyPythonCallbacksParser._expose_symbols_from_loaded_files(
            load_statements, filepath
        )

        self._symbols.update(symbols_loaded_from_files)

        exec(python, dict(self._symbols))

        # Perform this check after successful execution, so we know the python is valid (and should
        # tokenize properly!)
        # Note that this is incredibly poor sandboxing. There are many ways to get around it.
        # But it's sufficient to tell most users who aren't being actively malicious that they're doing
        # something wrong, and it has a low performance overhead.
        if "globs" in python or (
            self._build_file_imports_behavior != BuildFileImportsBehavior.allow
            and "import" in python
        ):
            io_wrapped_python = StringIO(python)
            for token in tokenize.generate_tokens(io_wrapped_python.readline):
                token_str = token[1]
                lineno, _ = token[2]

                self.check_for_deprecated_globs_usage(token_str, filepath, lineno)

                if token_str == "import":
                    if self._build_file_imports_behavior == BuildFileImportsBehavior.allow:
                        continue
                    elif self._build_file_imports_behavior == BuildFileImportsBehavior.warn:
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
