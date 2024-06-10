# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import itertools
import logging
import re
import threading
import tokenize
import traceback
import typing
from dataclasses import InitVar, dataclass, field
from difflib import get_close_matches
from io import StringIO
from pathlib import PurePath
from typing import Annotated, Any, Callable, Iterable, Mapping, TypeVar

import typing_extensions

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
from pants.util.memo import memoized_property
from pants.util.strutil import docstring, softwrap, strval

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class BuildFileSymbolsInfo:
    info: FrozenDict[str, BuildFileSymbolInfo]

    @classmethod
    def from_info(cls, *infos: Iterable[BuildFileSymbolInfo]) -> BuildFileSymbolsInfo:
        info = {}
        for symbol in itertools.chain.from_iterable(infos):
            if symbol.name not in info:
                info[symbol.name] = symbol
            elif symbol != info[symbol.name]:
                logger.warning(f"BUILD file symbol `{symbol.name}` conflict. Name already defined.")
                logger.debug(
                    f"BUILD file symbol conflict between:\n{info[symbol.name]} and {symbol}"
                )
        return cls(info=FrozenDict(info))

    @memoized_property
    def symbols(self) -> FrozenDict[str, Any]:
        return FrozenDict({name: symbol.value for name, symbol in self.info.items()})


@dataclass(frozen=True)
class BuildFilePreludeSymbols(BuildFileSymbolsInfo):
    referenced_env_vars: tuple[str, ...]

    @classmethod
    def create(cls, ns: Mapping[str, Any], env_vars: Iterable[str]) -> BuildFilePreludeSymbols:
        info = {}
        annotations = ns.get("__annotations__", {})
        for name, symb in ns.items():
            if name.startswith("_"):
                continue
            # We only need type hints via `annotations` for top-level values which doesn't work with `inspect`.
            info[name] = BuildFileSymbolInfo(name, symb, type_hints=annotations.get(name))
        return cls(info=FrozenDict(info), referenced_env_vars=tuple(sorted(env_vars)))


@dataclass(frozen=True)
class BuildFileSymbolInfo:
    name: str
    value: Any
    help: str | None = field(default=None, compare=False)
    signature: str | None = field(default=None, compare=False, init=False)
    type_hints: InitVar[Any] = None

    def __post_init__(self, type_hints: Any) -> None:
        annotated_type: type = type(self.value)
        help: str | None = self.help
        signature: str | None = None

        if type_hints is not None:
            if typing.get_origin(type_hints) is Annotated:
                annotated_type, *metadata = typing.get_args(type_hints)
                for meta in metadata:
                    if isinstance(meta, typing_extensions.Doc):  # type: ignore[attr-defined]
                        help = meta.documentation
                        break
            else:
                annotated_type = type_hints

        if help is None:
            if hasattr(self.value, "__name__"):
                help = inspect.getdoc(self.value)

        if self.help is None and isinstance(help, str):
            object.__setattr__(self, "help", softwrap(help))

        if callable(self.value):
            try:
                signature = str(inspect.signature(self.value))
            except ValueError:
                signature = None
        else:
            signature = f": {annotated_type.__name__}"
        object.__setattr__(self, "signature", signature)


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


class UnaddressableObjectError(MappingError):
    """Indicates an un-addressable object was found at the top level."""


class ParseState(threading.local):
    def __init__(self) -> None:
        self._defaults: BuildFileDefaultsParserState | None = None
        self._dependents_rules: BuildFileDependencyRulesParserState | None = None
        self._dependencies_rules: BuildFileDependencyRulesParserState | None = None
        self._filepath: str | None = None
        self._target_adaptors: list[TargetAdaptor] = []
        self._is_bootstrap: bool | None = None
        self._env_vars: EnvironmentVars | None = None
        self._symbols = tuple(
            BuildFileSymbolInfo(name, value)
            for name, value in (
                ("build_file_dir", self.build_file_dir),
                ("env", self.get_env),
                ("__defaults__", self.set_defaults),
                ("__dependents_rules__", self.set_dependents_rules),
                ("__dependencies_rules__", self.set_dependencies_rules),
            )
        )

    def reset(
        self,
        filepath: str,
        is_bootstrap: bool,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
        env_vars: EnvironmentVars,
    ) -> None:
        self._is_bootstrap = is_bootstrap
        self._defaults = defaults
        self._dependents_rules = dependents_rules
        self._dependencies_rules = dependencies_rules
        self._env_vars = env_vars
        self._filepath = filepath
        self._target_adaptors.clear()

    def add(self, target_adaptor: TargetAdaptor) -> None:
        self._target_adaptors.append(target_adaptor)

    def parsed_targets(self) -> list[TargetAdaptor]:
        return list(self._target_adaptors)

    def _prelude_check(self, name: str, value: T | None, closure_supported: bool = True) -> T:
        if value is not None:
            return value
        note = (
            (
                " If used in a prelude file, it must be within a function that is called from a BUILD"
                " file."
            )
            if closure_supported
            else ""
        )
        raise NameError(
            softwrap(
                f"""
                The BUILD file symbol `{name}` may only be used in BUILD files.{note}
                """
            )
        )

    def filepath(self) -> str:
        return self._prelude_check("build_file_dir", self._filepath)

    def build_file_dir(self) -> PurePath:
        """Returns the path to the directory of the current BUILD file.

        The returned value is an instance of `PurePath` to make path name manipulations easy.

        See: https://docs.python.org/3/library/pathlib.html#pathlib.PurePath
        """
        return PurePath(self.filepath()).parent

    @property
    def defaults(self) -> BuildFileDefaultsParserState:
        return self._prelude_check("__defaults__", self._defaults)

    @property
    def env_vars(self) -> EnvironmentVars:
        return self._prelude_check("env", self._env_vars)

    @property
    def is_bootstrap(self) -> bool:
        if self._is_bootstrap is None:
            raise AssertionError(
                "Internal error in Pants. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new"
            )
        return self._is_bootstrap

    def get_env(self, name: str, *args, **kwargs) -> Any:
        """Reference environment variable."""
        return self.env_vars.get(name, *args, **kwargs)

    @docstring(
        f"""Provide default field values.

        Learn more {doc_url("docs/using-pants/key-concepts/targets-and-build-files#field-default-values")}
        """
    )
    def set_defaults(
        self,
        *args: SetDefaultsT,
        ignore_unknown_fields: bool = False,
        ignore_unknown_targets: bool = False,
        **kwargs,
    ) -> None:
        self.defaults.set_defaults(
            *args,
            ignore_unknown_fields=self.is_bootstrap or ignore_unknown_fields,
            ignore_unknown_targets=self.is_bootstrap or ignore_unknown_targets,
            **kwargs,
        )

    def set_dependents_rules(self, *args, **kwargs) -> None:
        """Declare dependents rules."""
        if self._dependents_rules is not None:
            self._dependents_rules.set_dependency_rules(self.filepath(), *args, **kwargs)

    def set_dependencies_rules(self, *args, **kwargs) -> None:
        """Declare dependencies rules."""
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


class Registrar:
    def __init__(
        self,
        parse_state: ParseState,
        type_alias: str,
        field_types: tuple[type[Field], ...],
        help: str,
    ) -> None:
        self.__doc__ = help
        self._parse_state = parse_state
        self._type_alias = type_alias
        for field_type in field_types:
            registrar_field = RegistrarField(field_type, self._field_default_factory(field_type))
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

        This allows the use of the BUILD file symbols for the target types to be used un- quoted for
        the defaults dictionary.
        """
        return self._type_alias

    def __call__(self, **kwargs: Any) -> TargetAdaptor:
        if self._parse_state.is_bootstrap and any(
            isinstance(v, _UnrecognizedSymbol) for v in kwargs.values()
        ):
            # Remove any field values that are not recognized during the bootstrap phase.
            kwargs = {k: v for k, v in kwargs.items() if not isinstance(v, _UnrecognizedSymbol)}

        # Target names default to the name of the directory their BUILD file is in
        # (as long as it's not the root directory).
        if "name" not in kwargs:
            if not self._parse_state.filepath():
                raise UnaddressableObjectError(
                    "Targets in root-level BUILD files must be named explicitly."
                )
            kwargs["name"] = None

        frame = inspect.currentframe()
        source_line = frame.f_back.f_lineno if frame and frame.f_back else "??"
        kwargs["__description_of_origin__"] = f"{self._parse_state.filepath()}:{source_line}"
        raw_values = dict(self._parse_state.defaults.get(self._type_alias))
        raw_values.update(kwargs)
        target_adaptor = TargetAdaptor(self._type_alias, **raw_values)
        self._parse_state.add(target_adaptor)
        return target_adaptor

    def _field_default_factory(self, field_type: type[Field]) -> Callable[[], Any]:
        def resolve_field_default() -> Any:
            target_defaults = self._parse_state.defaults.get(self._type_alias)
            if target_defaults:
                for field_alias in (field_type.alias, field_type.deprecated_alias):
                    if field_alias and field_alias in target_defaults:
                        return target_defaults[field_alias]
            return field_type.default

        return resolve_field_default


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
        self._symbols_info, self._parse_state = self._generate_symbols(
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
    ) -> tuple[BuildFileSymbolsInfo, ParseState]:
        # N.B.: We re-use the thread local ParseState across symbols for performance reasons.
        # This allows a single construction of all symbols here that can be re-used for each BUILD
        # file parse with a reset of the ParseState for the calling thread.
        parse_state = ParseState()

        def create_registrar_for_target(alias: str) -> tuple[str, Registrar]:
            target_cls = registered_target_types.aliases_to_types[alias]
            return alias, Registrar(
                parse_state,
                alias,
                tuple(target_cls.class_field_types(union_membership)),
                strval(getattr(target_cls, "help", "")),
            )

        type_aliases = dict(map(create_registrar_for_target, registered_target_types.aliases))
        parse_context = ParseContext(
            build_root=build_root,
            type_aliases=type_aliases,
            filepath_oracle=parse_state,
        )

        symbols_info = BuildFileSymbolsInfo.from_info(
            parse_state._symbols,
            (
                BuildFileSymbolInfo(alias, registrar, help=registrar.__doc__)
                for alias, registrar in type_aliases.items()
            ),
            (BuildFileSymbolInfo(alias, value) for alias, value in object_aliases.objects.items()),
            (
                BuildFileSymbolInfo(alias, object_factory(parse_context))
                for alias, object_factory in object_aliases.context_aware_object_factories.items()
            ),
        )

        return symbols_info, parse_state

    @property
    def symbols_info(self) -> BuildFileSymbolsInfo:
        return self._symbols_info

    @property
    def symbols(self) -> FrozenDict[str, Any]:
        return self._symbols_info.symbols

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
            env_vars=env_vars,
        )

        global_symbols: dict[str, Any] = {
            **self.symbols,
            **extra_symbols.symbols,
        }

        if self.ignore_unrecognized_symbols:
            defined_symbols = set()
            while True:
                try:
                    code = compile(build_file_content, filepath, "exec", dont_inherit=True)
                    exec(code, global_symbols)
                except NameError as e:
                    bad_symbol = _extract_symbol_from_name_error(e)
                    if bad_symbol in defined_symbols:
                        # We have previously attempted to define this symbol, but have received
                        # another error for it. This can indicate that the symbol is being used
                        # from code which has already been compiled, such as builtin functions.
                        raise
                    defined_symbols.add(bad_symbol)

                    global_symbols[bad_symbol] = _UnrecognizedSymbol(bad_symbol)
                    self._parse_state.reset(
                        filepath=filepath,
                        is_bootstrap=is_bootstrap,
                        defaults=defaults,
                        dependents_rules=dependents_rules,
                        dependencies_rules=dependencies_rules,
                        env_vars=env_vars,
                    )
                    continue
                break

            error_on_imports(build_file_content, filepath)
            return self._parse_state.parsed_targets()

        try:
            code = compile(build_file_content, filepath, "exec", dont_inherit=True)
            exec(code, global_symbols)
        except NameError as e:
            frame = traceback.extract_tb(e.__traceback__, limit=-1)[0]
            msg = (  # Capitalise first letter of NameError message.
                e.args[0][0].upper() + e.args[0][1:]
            )
            location = f":{frame.name}" if frame.name != "<module>" else ""
            original = f"{frame.filename}:{frame.lineno}{location}: {msg}"
            help_str = softwrap(
                f"""
                If you expect to see more symbols activated in the below list, refer to
                {doc_url('docs/using-pants/key-concepts/backends')} for all available backends to activate.
                """
            )
            valid_symbols = sorted(s for s in global_symbols.keys() if s != "__builtins__")
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
            f"\n\nInstead, consider writing a plugin ({doc_url('docs/writing-plugins/overview')})."
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


class _UnrecognizedSymbol:
    """Allows us to not choke on unrecognized symbols, including when they're called as functions.

    During bootstrap macros are not loaded and if used in field values to environment targets (which
    are parsed during the bootstrap phase) those fields will get instances of this class as field
    values.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.args: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}

    def __hash__(self) -> int:
        return hash(self.name)

    def __call__(self, *args, **kwargs) -> _UnrecognizedSymbol:
        self.args = args
        self.kwargs = kwargs
        return self

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, _UnrecognizedSymbol)
            and other.name == self.name
            and other.args == self.args
            and other.kwargs == self.kwargs
        )

    def __repr__(self) -> str:
        args = ", ".join(map(repr, self.args))
        kwargs = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items())
        signature = ", ".join(s for s in (args, kwargs) if s)
        return f"{self.name}({signature})"


# Customize the type name presented by the InvalidFieldTypeException.
_UnrecognizedSymbol.__name__ = "<unrecognized symbol>"
