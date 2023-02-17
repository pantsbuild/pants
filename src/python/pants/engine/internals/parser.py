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
from typing import Any, Callable

from pants.base.deprecated import warn_or_error
from pants.base.exceptions import MappingError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.env_vars import EnvironmentVars
from pants.engine.internals.defaults import BuildFileDefaultsParserState, SetDefaultsT
from pants.engine.internals.dep_rules import BuildFileDependencyRulesParserState
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import Field, ImmutableValue, RegisteredTargetTypes
from pants.engine.unions import UnionMembership
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
        self._is_bootstrap: bool | None = None

    def reset(
        self,
        filepath: str,
        is_bootstrap: bool,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
    ) -> None:
        self._is_bootstrap = is_bootstrap
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

    @property
    def is_bootstrap(self) -> bool:
        if self._is_bootstrap is None:
            raise AssertionError(
                "Internal error in Pants. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new"
            )
        return self._is_bootstrap

    def set_defaults(
        self, *args: SetDefaultsT, ignore_unknown_fields: bool = False, **kwargs
    ) -> None:
        self.defaults.set_defaults(
            *args, ignore_unknown_fields=self.is_bootstrap or ignore_unknown_fields, **kwargs
        )

    def set_dependents_rules(self, *args, **kwargs) -> None:
        if self._dependents_rules is not None:
            self._dependents_rules.set_dependency_rules(self.filepath(), *args, **kwargs)

    def set_dependencies_rules(self, *args, **kwargs) -> None:
        if self._dependencies_rules is not None:
            self._dependencies_rules.set_dependency_rules(self.filepath(), *args, **kwargs)


class RegistrarField:
    __slots__ = ("_field_type", "_default")

    def __init__(self, field_type: type[Field], default: Callable[[], Any]) -> None:
        self._field_type = field_type
        self._default = default

    @property
    def default(self) -> ImmutableValue:
        return self._default()


class Parser:
    def __init__(
        self,
        *,
        build_root: str,
        registered_target_types: RegisteredTargetTypes,
        union_membership: UnionMembership,
        object_aliases: BuildFileAliases,
        ignore_unrecognized_symbols: bool,
    ) -> None:
        self._symbols, self._parse_state = self._generate_symbols(
            build_root,
            object_aliases,
            registered_target_types,
            union_membership,
        )
        self.ignore_unrecognized_symbols = ignore_unrecognized_symbols

    @staticmethod
    def _generate_symbols(
        build_root: str,
        object_aliases: BuildFileAliases,
        registered_target_types: RegisteredTargetTypes,
        union_membership: UnionMembership,
    ) -> tuple[FrozenDict[str, Any], ParseState]:
        # N.B.: We re-use the thread local ParseState across symbols for performance reasons.
        # This allows a single construction of all symbols here that can be re-used for each BUILD
        # file parse with a reset of the ParseState for the calling thread.
        parse_state = ParseState()

        class Registrar:
            def __init__(self, type_alias: str) -> None:
                self._type_alias = type_alias
                for field_type in registered_target_types.aliases_to_types[
                    type_alias
                ].class_field_types(union_membership):
                    registrar_field = RegistrarField(
                        field_type, self._field_default_factory(field_type)
                    )
                    setattr(self, field_type.alias, registrar_field)
                    if field_type.deprecated_alias:

                        def deprecated_field(self):
                            # TODO(17720) Support fixing automatically with `build-file` deprecation
                            # fixer.
                            warn_or_error(
                                removal_version=field_type.deprecated_alias_removal_version,
                                entity=f"the field name {field_type.deprecated_alias}",
                                hint=(
                                    f"Instead, use `{type_alias}.{field_type.alias}`, which "
                                    "behaves the same."
                                ),
                            )
                            return registrar_field

                        setattr(self, field_type.deprecated_alias, property(deprecated_field))

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

            def _field_default_factory(self, field_type: type[Field]) -> Callable[[], Any]:
                def resolve_field_default() -> Any:
                    target_defaults = parse_state.defaults.get(self._type_alias)
                    if target_defaults:
                        for field_alias in (field_type.alias, field_type.deprecated_alias):
                            if field_alias and field_alias in target_defaults:
                                return target_defaults[field_alias]
                    return field_type.default

                return resolve_field_default

        symbols: dict[str, Any] = {
            **object_aliases.objects,
            "build_file_dir": lambda: PurePath(parse_state.filepath()).parent,
            "__defaults__": parse_state.set_defaults,
            "__dependents_rules__": parse_state.set_dependents_rules,
            "__dependencies_rules__": parse_state.set_dependencies_rules,
        }
        symbols.update((alias, Registrar(alias)) for alias in registered_target_types.aliases)

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
        env_vars: EnvironmentVars,
        is_bootstrap: bool,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
    ) -> list[TargetAdaptor]:
        self._parse_state.reset(
            filepath=filepath,
            is_bootstrap=is_bootstrap,
            defaults=defaults,
            dependents_rules=dependents_rules,
            dependencies_rules=dependencies_rules,
        )

        global_symbols: dict[str, Any] = {
            "env": env_vars.get,
            **self._symbols,
            **extra_symbols.symbols,
        }

        if self.ignore_unrecognized_symbols:
            defined_symbols = set()
            while True:
                try:
                    exec(build_file_content, global_symbols)
                except NameError as e:
                    bad_symbol = _extract_symbol_from_name_error(e)
                    if bad_symbol in defined_symbols:
                        # We have previously attempted to define this symbol, but have received
                        # another error for it. This can indicate that the symbol is being used
                        # from code which has already been compiled, such as builtin functions.
                        raise
                    defined_symbols.add(bad_symbol)

                    global_symbols[bad_symbol] = _unrecognized_symbol_func
                    self._parse_state.reset(
                        filepath=filepath,
                        is_bootstrap=is_bootstrap,
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
            "BUILD files and macros (that act like a normal BUILD file) because they can easily "
            "break Pants caching and lead to stale results. "
            f"\n\nInstead, consider writing a plugin ({doc_url('plugins-overview')})."
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
