# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import threading
import tokenize
from dataclasses import dataclass
from difflib import get_close_matches
from io import StringIO
from pathlib import PurePath
from typing import Any, Iterable

from pants.base.exceptions import MappingError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.defaults import BuildFileDefaultsParserState, SetDefaultsT
from pants.engine.internals.dep_rules import BuildFileDependencyRulesParserState
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class BuildFilePreludeSymbols:
    symbols: FrozenDict[str, Any]


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class ParseState(threading.local):
    def __init__(self):
        self._defaults: BuildFileDefaultsParserState | None = None
        self._dependents_rules: BuildFileDependencyRulesParserState | None = None
        self._dependencies_rules: BuildFileDependencyRulesParserState | None = None
        self._filepath: str | None = None
        self._target_adaptors: list[TargetAdaptor] = []

    def reset(
        self,
        filepath: str,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
    ) -> None:
        self._defaults = defaults
        self._dependents_rules = dependents_rules
        self._dependencies_rules = dependencies_rules
        self._filepath = filepath
        self._target_adaptors.clear()

    def add(self, target_adaptor: TargetAdaptor) -> None:
        self._target_adaptors.append(target_adaptor)

    def filepath(self) -> str:
        if self._filepath is None:
            raise AssertionError(
                "The BUILD file filepath was accessed before being set. This indicates a "
                "programming error in Pants. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new."
            )
        return self._filepath

    def parsed_targets(self) -> list[TargetAdaptor]:
        return list(self._target_adaptors)

    @property
    def defaults(self) -> BuildFileDefaultsParserState:
        if self._defaults is None:
            raise AssertionError(
                "The BUILD file __defaults__ was accessed before being set. This indicates a "
                "programming error in Pants. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new."
            )
        return self._defaults

    def set_defaults(self, *args: SetDefaultsT, **kwargs) -> None:
        self.defaults.set_defaults(*args, **kwargs)

    def set_dependents_rules(self, *args, **kwargs) -> None:
        if self._dependents_rules is not None:
            self._dependents_rules.set_dependency_rules(self.filepath(), *args, **kwargs)

    def set_dependencies_rules(self, *args, **kwargs) -> None:
        if self._dependencies_rules is not None:
            self._dependencies_rules.set_dependency_rules(self.filepath(), *args, **kwargs)


class Parser:
    def __init__(
        self,
        *,
        build_root: str,
        target_type_aliases: Iterable[str],
        object_aliases: BuildFileAliases,
        ignore_unrecognized_symbols: bool,
    ) -> None:
        self._symbols, self._parse_state = self._generate_symbols(
            build_root, target_type_aliases, object_aliases
        )
        self.ignore_unrecognized_symbols = ignore_unrecognized_symbols

    @staticmethod
    def _generate_symbols(
        build_root: str,
        target_type_aliases: Iterable[str],
        object_aliases: BuildFileAliases,
    ) -> tuple[FrozenDict[str, Any], ParseState]:
        # N.B.: We re-use the thread local ParseState across symbols for performance reasons.
        # This allows a single construction of all symbols here that can be re-used for each BUILD
        # file parse with a reset of the ParseState for the calling thread.
        parse_state = ParseState()

        class Registrar:
            def __init__(self, type_alias: str) -> None:
                self._type_alias = type_alias

            def __str__(self) -> str:
                """The BuildFileDefaultsParserState.set_defaults() rely on string inputs.

                This allows the use of the BUILD file symbols for the target types to be used un-
                quoted for the defaults dictionary.
                """
                return self._type_alias

            def __call__(self, **kwargs: Any) -> TargetAdaptor:
                # Target names default to the name of the directory their BUILD file is in
                # (as long as it's not the root directory).
                if "name" not in kwargs:
                    if not parse_state.filepath():
                        raise UnaddressableObjectError(
                            "Targets in root-level BUILD files must be named explicitly."
                        )
                    kwargs["name"] = None

                raw_values = dict(parse_state.defaults.get(self._type_alias))
                raw_values.update(kwargs)
                target_adaptor = TargetAdaptor(self._type_alias, **raw_values)
                parse_state.add(target_adaptor)
                return target_adaptor

        symbols: dict[str, Any] = {
            **object_aliases.objects,
            "build_file_dir": lambda: PurePath(parse_state.filepath()).parent,
            "__defaults__": parse_state.set_defaults,
            "__dependents_rules__": parse_state.set_dependents_rules,
            "__dependencies_rules__": parse_state.set_dependencies_rules,
        }
        symbols.update((alias, Registrar(alias)) for alias in target_type_aliases)

        parse_context = ParseContext(
            build_root=build_root, type_aliases=symbols, filepath_oracle=parse_state
        )
        for alias, object_factory in object_aliases.context_aware_object_factories.items():
            symbols[alias] = object_factory(parse_context)

        return FrozenDict(symbols), parse_state

    @property
    def builtin_symbols(self) -> FrozenDict[str, Any]:
        return self._symbols

    def parse(
        self,
        filepath: str,
        build_file_content: str,
        extra_symbols: BuildFilePreludeSymbols,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
    ) -> list[TargetAdaptor]:
        self._parse_state.reset(
            filepath=filepath,
            defaults=defaults,
            dependents_rules=dependents_rules,
            dependencies_rules=dependencies_rules,
        )

        global_symbols = {**self._symbols, **extra_symbols.symbols}

        if self.ignore_unrecognized_symbols:
            while True:
                try:
                    exec(build_file_content, global_symbols)
                except NameError as e:
                    bad_symbol = _extract_symbol_from_name_error(e)
                    global_symbols[bad_symbol] = _unrecognized_symbol_func
                    self._parse_state.reset(
                        filepath=filepath,
                        defaults=defaults,
                        dependents_rules=dependents_rules,
                        dependencies_rules=dependencies_rules,
                    )
                    continue
                break

            error_on_imports(build_file_content, filepath)
            return self._parse_state.parsed_targets()

        try:
            exec(build_file_content, global_symbols)
        except NameError as e:
            valid_symbols = sorted(s for s in global_symbols.keys() if s != "__builtins__")
            original = e.args[0].capitalize()
            help_str = softwrap(
                f"""
                If you expect to see more symbols activated in the below list, refer to
                {doc_url('enabling-backends')} for all available backends to activate.
                """
            )

            candidates = get_close_matches(build_file_content, valid_symbols)
            if candidates:
                if len(candidates) == 1:
                    formatted_candidates = candidates[0]
                elif len(candidates) == 2:
                    formatted_candidates = " or ".join(candidates)
                else:
                    formatted_candidates = f"{', '.join(candidates[:-1])}, or {candidates[-1]}"
                help_str = f"Did you mean {formatted_candidates}?\n\n" + help_str
            raise ParseError(
                f"{original}.\n\n{help_str}\n\nAll registered symbols: {valid_symbols}"
            )

        error_on_imports(build_file_content, filepath)
        return self._parse_state.parsed_targets()


def error_on_imports(build_file_content: str, filepath: str) -> None:
    # This is poor sandboxing; there are many ways to get around this. But it's sufficient to tell
    # users who aren't malicious that they're doing something wrong, and it has a low performance
    # overhead.
    if "import" not in build_file_content:
        return
    io_wrapped_python = StringIO(build_file_content)
    for token in tokenize.generate_tokens(io_wrapped_python.readline):
        token_str = token[1]
        lineno, _ = token[2]
        if token_str != "import":
            continue
        raise ParseError(
            f"Import used in {filepath} at line {lineno}. Import statements are banned in "
            "BUILD files because they can easily break Pants caching and lead to stale results. "
            f"\n\nInstead, consider writing a macro ({doc_url('macros')}) or "
            f"writing a plugin ({doc_url('plugins-overview')}."
        )


def _extract_symbol_from_name_error(err: NameError) -> str:
    result = re.match(r"^name '(\w*)'", err.args[0])
    if result is None:
        raise AssertionError(
            softwrap(
                f"""
                Failed to extract symbol from NameError: {err}

                Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose
                """
            )
        )
    return result.group(1)


def _unrecognized_symbol_func(**kwargs):
    """Allows us to not choke on unrecognized symbols, including when they're called as
    functions."""
