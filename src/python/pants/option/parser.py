# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import copy
import inspect
import json
import re
import typing
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Type

import yaml

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import validate_deprecation_semver, warn_or_error
from pants.engine.internals.native_engine import PyOptionId, PyOptionParser
from pants.option.custom_types import (
    DictValueComponent,
    ListValueComponent,
    UnsetBool,
    dir_option,
    file_option,
    shell_str,
    target_option,
)
from pants.option.errors import (
    BooleanConversionError,
    BooleanOptionNameWithNo,
    DefaultMemberValueType,
    DefaultValueType,
    FromfileError,
    HelpType,
    ImplicitValIsNone,
    InvalidKwarg,
    InvalidKwargNonGlobalScope,
    InvalidMemberType,
    MemberTypeNotAllowed,
    MutuallyExclusiveOptionError,
    NoOptionNames,
    OptionAlreadyRegistered,
    OptionNameDoubleDash,
    ParseError,
    PassthroughType,
    RegistrationError,
    UnknownFlagsError,
)
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION, ScopeInfo
from pants.util.strutil import softwrap
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo


@dataclass(frozen=True)
class OptionValueHistory:
    ranked_values: tuple[RankedValue, ...]

    @property
    def final_value(self) -> RankedValue:
        return self.ranked_values[-1]


class Parser:
    """An argument parser."""

    @staticmethod
    def is_bool(kwargs: Mapping[str, Any]) -> bool:
        type_arg = kwargs.get("type")
        if type_arg is None:
            return False
        if type_arg is bool:
            return True
        try:
            return typing.get_type_hints(type_arg).get("return") is bool
        except TypeError:
            return False

    @staticmethod
    def ensure_bool(val: bool | str) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            s = val.lower()
            if s == "true":
                return True
            if s == "false":
                return False
            raise BooleanConversionError(f'Got "{val}". Expected "True" or "False".')
        raise BooleanConversionError(f"Got {val}. Expected True or False.")

    @classmethod
    def _invert(cls, s: bool | str | None) -> bool | None:
        if s is None:
            return None
        b = cls.ensure_bool(s)
        return not b

    @classmethod
    def scope_str(cls, scope: str) -> str:
        return "global scope" if scope == GLOBAL_SCOPE else f"scope '{scope}'"

    def __init__(
        self,
        option_parser: PyOptionParser,
        scope_info: ScopeInfo,
    ) -> None:
        """Create a Parser instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param scope_info: the scope this parser acts for.
        """
        self._option_parser = option_parser
        self._scope_info = scope_info
        self._scope = self._scope_info.scope

        # All option args registered with this parser. Used to prevent conflicts.
        self._known_args: set[str] = set()

        # List of (args, kwargs) registration pairs, exactly as captured at registration time.
        self._option_registrations: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    @property
    def scope_info(self) -> ScopeInfo:
        return self._scope_info

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def known_scoped_args(self) -> frozenset[str]:
        prefix = f"{self.scope}-" if self.scope != GLOBAL_SCOPE else ""
        return frozenset(f"--{prefix}{arg.lstrip('--')}" for arg in self._known_args)

    @dataclass(frozen=True)
    class ParseArgsRequest:
        flag_value_map: dict[str, list[Any]]
        namespace: OptionValueContainerBuilder
        passthrough_args: list[str]
        allow_unknown_flags: bool

        def __init__(
            self,
            flags_in_scope: Iterable[str],
            namespace: OptionValueContainerBuilder,
            passthrough_args: list[str],
            allow_unknown_flags: bool,
        ) -> None:
            """
            :param flags_in_scope: Iterable of arg strings to parse into flag values.
            :param namespace: The object to register the flag values on
            """
            object.__setattr__(self, "flag_value_map", self._create_flag_value_map(flags_in_scope))
            object.__setattr__(self, "namespace", namespace)
            object.__setattr__(self, "passthrough_args", passthrough_args)
            object.__setattr__(self, "allow_unknown_flags", allow_unknown_flags)

        @staticmethod
        def _create_flag_value_map(flags: Iterable[str]) -> DefaultDict[str, list[str | None]]:
            """Returns a map of flag -> list of values, based on the given flag strings.

            None signals no value given (e.g., -x, --foo). The value is a list because the user may
            specify the same flag multiple times, and that's sometimes OK (e.g., when appending to
            list- valued options).
            """
            flag_value_map: DefaultDict[str, list[str | None]] = defaultdict(list)
            for flag in flags:
                flag_val: str | None
                key, has_equals_sign, flag_val = flag.partition("=")
                if not has_equals_sign:
                    if not flag.startswith("--"):  # '-xfoo' style.
                        key = flag[0:2]
                        flag_val = flag[2:]
                    if not flag_val:
                        # Either a short option with no value or a long option with no equals sign.
                        # Important so we can distinguish between no value ('--foo') and setting to an empty
                        # string ('--foo='), for options with an implicit_value.
                        flag_val = None
                flag_value_map[key].append(flag_val)
            return flag_value_map

    def parse_args(self, parse_args_request: ParseArgsRequest) -> OptionValueContainer:
        """Set values for this parser's options on the namespace object.

        :raises: :class:`ParseError` if any flags weren't recognized.
        """

        flag_value_map = parse_args_request.flag_value_map
        namespace = parse_args_request.namespace

        mutex_map: DefaultDict[str, list[str]] = defaultdict(list)
        for args, kwargs in self._option_registrations:
            self._validate(args, kwargs)
            dest = self.parse_dest(*args, **kwargs)

            for arg in args:
                # If the user specified --no-foo on the cmd line, treat it as if the user specified
                # --foo, but with the inverse value.
                if self.is_bool(kwargs):
                    inverse_arg = self._inverse_arg(arg)
                    if inverse_arg in flag_value_map:
                        flag_value_map[arg] = [self._invert(v) for v in flag_value_map[inverse_arg]]
                        del flag_value_map[inverse_arg]

                if arg in flag_value_map:
                    del flag_value_map[arg]

            # Get the value for this option, falling back to defaults as needed.
            try:
                val, rank = self._compute_value(dest, kwargs, parse_args_request.passthrough_args)
            except Exception as e:
                raise ParseError(
                    f"Error computing value for `{dest}` in {self._scope_str()}:\n{e}"
                ) from e

            # If the option is explicitly given, check deprecation and mutual exclusion.
            if rank > Rank.HARDCODED:
                self._check_deprecated(dest, kwargs)
                mutex_dest = kwargs.get("mutually_exclusive_group")
                mutex_map_key = mutex_dest or dest
                mutex_map[mutex_map_key].append(dest)
                if len(mutex_map[mutex_map_key]) > 1:
                    raise MutuallyExclusiveOptionError(
                        softwrap(
                            f"""
                            Can only provide one of these mutually exclusive options in
                            {self._scope_str()}, but multiple given:
                            {', '.join(mutex_map[mutex_map_key])}
                            """
                        )
                    )

            setattr(namespace, dest, (val, rank))

        if not parse_args_request.allow_unknown_flags and flag_value_map:
            # There were unconsumed flags.
            raise UnknownFlagsError(tuple(flag_value_map.keys()), self.scope)
        return namespace.build()

    def option_registrations_iter(self):
        """Returns an iterator over the normalized registration arguments of each option in this
        parser.

        Useful for generating help and other documentation.

        Each yielded item is an (args, kwargs) pair, as passed to register(), except that kwargs
        will be normalized in the following ways:
          - It will always have 'dest' explicitly set.
          - It will always have 'default' explicitly set, and the value will be a RankedValue.
        """

        def normalize_kwargs(orig_args, orig_kwargs):
            nkwargs = copy.copy(orig_kwargs)
            dest = self.parse_dest(*orig_args, **nkwargs)
            nkwargs["dest"] = dest
            if not ("default" in nkwargs and isinstance(nkwargs["default"], RankedValue)):
                type_arg = nkwargs.get("type", str)
                member_type = nkwargs.get("member_type", str)
                default_val = self.to_value_type(nkwargs.get("default"), type_arg, member_type)
                if isinstance(default_val, (ListValueComponent, DictValueComponent)):
                    default_val = default_val.val
                nkwargs["default"] = RankedValue(Rank.HARDCODED, default_val)
            return nkwargs

        # Yield our directly-registered options.
        for args, kwargs in self._option_registrations:
            normalized_kwargs = normalize_kwargs(args, kwargs)
            yield args, normalized_kwargs

    def register(self, *args, **kwargs) -> None:
        """Register an option."""
        if args:
            dest = self.parse_dest(*args, **kwargs)
            self._check_deprecated(dest, kwargs, print_warning=False)

        if self.is_bool(kwargs):
            default = kwargs.get("default")
            if default is None:
                # Unless a tri-state bool is explicitly opted into with the `UnsetBool` default value,
                # boolean options always have an implicit boolean-typed default. We make that default
                # explicit here.
                kwargs["default"] = not self.ensure_bool(kwargs.get("implicit_value", True))
            elif default is UnsetBool:
                kwargs["default"] = None

        # Record the args. We'll do the underlying parsing on-demand.
        self._option_registrations.append((args, kwargs))

        # Look for direct conflicts.
        for arg in args:
            if arg in self._known_args:
                raise OptionAlreadyRegistered(self.scope, arg)
        self._known_args.update(args)

    def _check_deprecated(self, dest: str, kwargs, print_warning: bool = True) -> None:
        """Checks option for deprecation and issues a warning/error if necessary."""
        removal_version = kwargs.get("removal_version", None)
        if removal_version is not None:
            warn_or_error(
                removal_version=removal_version,
                entity=f"option '{dest}' in {self._scope_str()}",
                start_version=kwargs.get("deprecation_start_version", None),
                hint=kwargs.get("removal_hint", None),
                print_warning=print_warning,
            )

    _allowed_registration_kwargs = {
        "type",
        "member_type",
        "choices",
        "dest",
        "default",
        "default_help_repr",
        "implicit_value",
        "metavar",
        "help",
        "advanced",
        "fingerprint",
        "removal_version",
        "removal_hint",
        "deprecation_start_version",
        "fromfile",
        "mutually_exclusive_group",
        "daemon",
        "passthrough",
        "environment_aware",
    }

    _allowed_member_types = {
        str,
        int,
        float,
        dict,
        dir_option,
        file_option,
        target_option,
        shell_str,
    }

    def _validate(self, args, kwargs) -> None:
        """Validate option registration arguments."""

        def error(
            exception_type: type[RegistrationError],
            arg_name: str | None = None,
            **msg_kwargs,
        ) -> None:
            if arg_name is None:
                arg_name = args[0] if args else "<unknown>"
            raise exception_type(self.scope, arg_name, **msg_kwargs)

        if not args:
            error(NoOptionNames)
        # Validate args.
        for arg in args:
            # We ban short args like `-x`, except for special casing the global option `-l`.
            if not arg.startswith("--") and not (self.scope == GLOBAL_SCOPE and arg == "-l"):
                error(OptionNameDoubleDash, arg_name=arg)

        # Validate kwargs.
        if "implicit_value" in kwargs and kwargs["implicit_value"] is None:
            error(ImplicitValIsNone)
        type_arg = kwargs.get("type", str)
        if "member_type" in kwargs and type_arg != list:
            error(MemberTypeNotAllowed, type_=type_arg.__name__)
        member_type = kwargs.get("member_type", str)
        is_enum = inspect.isclass(member_type) and issubclass(member_type, Enum)
        if not is_enum and member_type not in self._allowed_member_types:
            error(InvalidMemberType, member_type=member_type.__name__)

        help_arg = kwargs.get("help")
        if help_arg is not None and not isinstance(help_arg, str):
            error(HelpType, help_type=type(help_arg).__name__)

        # check type of default value
        default_value = kwargs.get("default")
        if default_value is not None:
            if isinstance(default_value, str) and type_arg != str:
                # attempt to parse default value, for correctness..
                # custom function types may implement their own validation
                default_value = self.to_value_type(default_value, type_arg, member_type)
                if hasattr(default_value, "val"):
                    default_value = default_value.val

                # fall through to type check, to verify that custom types returned a value of correct type

            if isinstance(type_arg, type) and not isinstance(default_value, type_arg):
                error(
                    DefaultValueType,
                    option_type=type_arg.__name__,
                    default_value=kwargs["default"],
                    value_type=type(default_value).__name__,
                )

            # verify list member types (this is not done by the custom list value type)
            if type_arg == list:
                for member_val in default_value:
                    if not isinstance(member_type, type):
                        # defer value validation to custom type
                        member_type(member_val)

                    elif not isinstance(member_val, member_type):
                        error(
                            DefaultMemberValueType,
                            member_type=member_type.__name__,
                            member_value=member_val,
                            value_type=type(member_val).__name__,
                        )

        if (
            "passthrough" in kwargs
            and kwargs["passthrough"]
            and (type_arg != list or member_type not in (shell_str, str))
        ):
            error(PassthroughType)

        for kwarg in kwargs:
            if kwarg not in self._allowed_registration_kwargs:
                error(InvalidKwarg, kwarg=kwarg)

            # Ensure `daemon=True` can't be passed on non-global scopes.
            if kwarg == "daemon" and self._scope != GLOBAL_SCOPE:
                error(InvalidKwargNonGlobalScope, kwarg=kwarg)

        removal_version = kwargs.get("removal_version")
        if removal_version is not None:
            validate_deprecation_semver(removal_version, "removal version")

    _ENV_SANITIZER_RE = re.compile(r"[.-]")

    @staticmethod
    def parse_dest(*args, **kwargs):
        """Return the dest for an option registration.

        If an explicit `dest` is specified, returns that and otherwise derives a default from the
        option flags where '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.

        The dest is used for:
          - The name of the field containing the option value.
          - The key in the config file.
          - Computing the name of the env var used to set the option name.
        """
        dest = kwargs.get("dest")
        if dest:
            return dest
        # No explicit dest, so compute one based on the first long arg, or the short arg
        # if that's all there is.
        arg = next((a for a in args if a.startswith("--")), args[0])
        return arg.lstrip("-").replace("-", "_")

    @staticmethod
    def _convert_member_type(member_type, value):
        if member_type == dict:
            return DictValueComponent.create(value).val
        try:
            return member_type(value)
        except ValueError as error:
            raise ParseError(str(error))

    @classmethod
    def to_value_type(cls, val_str, type_arg, member_type):
        """Convert a string to a value of the option's type."""
        if val_str is None:
            return None
        if type_arg == bool:
            return cls.ensure_bool(val_str)
        try:
            if type_arg == list:
                return ListValueComponent.create(val_str, member_type=member_type)
            if type_arg == dict:
                return DictValueComponent.create(val_str)
            return type_arg(val_str)
        except (TypeError, ValueError) as e:
            if issubclass(type_arg, Enum):
                choices = ", ".join(f"{choice.value}" for choice in type_arg)
                raise ParseError(f"Invalid choice '{val_str}'. Choose from: {choices}")
            raise ParseError(
                f"Error applying type '{type_arg.__name__}' to option value '{val_str}': {e}"
            )

    @classmethod
    def get_env_var_names(cls, scope: str, dest: str):
        # Get value from environment, and capture details about its derivation.
        udest = dest.upper()
        if scope == GLOBAL_SCOPE:
            # For convenience, we allow three forms of env var for global scope options.
            # The fully-specified env var is PANTS_GLOBAL_FOO, which is uniform with PANTS_<SCOPE>_FOO
            # for all the other scopes.  However we also allow simply PANTS_FOO. And if the option name
            # itself starts with 'pants-' then we also allow simply FOO. E.g., PANTS_WORKDIR instead of
            # PANTS_PANTS_WORKDIR or PANTS_GLOBAL_PANTS_WORKDIR. We take the first specified value we
            # find, in this order: PANTS_GLOBAL_FOO, PANTS_FOO, FOO.
            env_vars = [f"PANTS_GLOBAL_{udest}", f"PANTS_{udest}"]
            if udest.startswith("PANTS_"):
                env_vars.append(udest)
        else:
            sanitized_env_var_scope = cls._ENV_SANITIZER_RE.sub("_", scope.upper())
            env_vars = [f"PANTS_{sanitized_env_var_scope}_{udest}"]
        return env_vars

    def _compute_value(self, dest, kwargs, passthru_arg_strs) -> tuple[Any, Rank]:
        """Compute the value to use for an option.

        The source of the value is chosen according to the ranking in Rank.
        """
        type_arg = kwargs.get("type", str)
        member_type = kwargs.get("member_type", str)
        default = kwargs.get("default")
        val: Any

        # Helper function to expand a fromfile=True value string, if needed.
        # May return a string or a dict/list decoded from a json/yaml file.
        def atfile_expand(val_or_str):
            if (
                kwargs.get("fromfile", True)
                and isinstance(val_or_str, str)
                and val_or_str.startswith("@")
            ):
                if val_or_str.startswith("@@"):  # Support a literal @ for fromfile values via @@.
                    return val_or_str[1:]
                else:
                    fromfile = val_or_str[1:]
                    try:
                        contents = Path(get_buildroot(), fromfile).read_text()
                        if fromfile.endswith(".json"):
                            return json.loads(contents)
                        elif fromfile.endswith(".yml") or fromfile.endswith(".yaml"):
                            return yaml.safe_load(contents)
                        else:
                            return contents.strip()
                    except (OSError, ValueError, yaml.YAMLError) as e:
                        raise FromfileError(
                            f"Failed to read {dest} in {self._scope_str()} from file {fromfile}: {e!r}"
                        )
            else:
                return val_or_str

        # TODO: Pass short flag name.
        option_id = PyOptionId(*dest.split("_"), scope=(self._scope or None))

        if type_arg == bool:
            val, source = self._option_parser.parse_bool(option_id, default or False)
        elif type_arg == list:
            val, source = self._option_parser.parse_from_string_list(
                option_id, default or [], lambda x: member_type(x)
            )
        elif type_arg == dict:

            def parse_dict_literal(x):
                val = atfile_expand(x)
                return ast.literal_eval(val) if isinstance(val, str) else val

            val, source = self._option_parser.parse_from_string_dict(
                option_id,
                default or {},
                lambda x: member_type(x),
                parse_dict_literal,
            )
        elif type_arg == Optional[int]:
            val, source = self._option_parser.parse_int_optional(option_id, default)
        elif type_arg == Optional[float]:
            val, source = self._option_parser.parse_float_optional(option_id, default)
        elif type_arg == int:
            if default is None:
                warn_or_error(
                    "2.20.0.dev0",
                    f"Option `{dest}` in `{self._scope_str()}` with type `int` and a default of `None`",
                    "Use `type=Optional[int]` for this option, or give it a default value.",
                )
                val, source = self._option_parser.parse_int_optional(option_id, default)
            else:
                val, source = self._option_parser.parse_int(option_id, default)
        elif type_arg == float:
            if default is None:
                warn_or_error(
                    "2.20.0.dev0",
                    f"Option `{dest}` in `{self._scope_str()}` with type `float` and a default of `None`",
                    "Use `type=Optional[float]` for this option, or give it a default value.",
                )
                val, source = self._option_parser.parse_float_optional(option_id, default)
            else:
                val, source = self._option_parser.parse_float(option_id, default)
        elif inspect.isclass(type_arg) and issubclass(type_arg, Enum):
            val, source = self._option_parser.parse_from_string(
                option_id, default, lambda x: type_arg(x)
            )
        else:
            val, source = self._option_parser.parse_from_string(
                option_id, default, lambda x: type_arg(x)
            )

        # Helper function to check various validity constraints on final option values.
        def check_scalar_value(val):
            if val is None:
                return
            choices = kwargs.get("choices")
            if choices is None and "type" in kwargs:
                if inspect.isclass(type_arg) and issubclass(type_arg, Enum):
                    choices = list(type_arg)
            if choices is not None and val not in choices:
                raise ParseError(
                    softwrap(
                        f"""
                        `{val}` is not an allowed value for option {dest} in {self._scope_str()}.
                        Must be one of: {choices}
                        """
                    )
                )
            elif type_arg == file_option:
                check_file_exists(val)
            elif type_arg == dir_option:
                check_dir_exists(val)

        def check_file_exists(val) -> None:
            error_prefix = f"File value `{val}` for option `{dest}` in `{self._scope_str()}`"
            try:
                path = Path(val)
                path_with_buildroot = Path(get_buildroot(), val)
            except TypeError:
                raise ParseError(f"{error_prefix} cannot be parsed as a file path.")
            if not path.is_file() and not path_with_buildroot.is_file():
                raise ParseError(f"{error_prefix} does not exist.")

        def check_dir_exists(val) -> None:
            error_prefix = f"Directory value `{val}` for option `{dest}` in `{self._scope_str()}`"
            try:
                path = Path(val)
                path_with_buildroot = Path(get_buildroot(), val)
            except TypeError:
                raise ParseError(f"{error_prefix} cannot be parsed as a directory path.")
            if not path.is_dir() and not path_with_buildroot.is_dir():
                raise ParseError(f"{error_prefix} does not exist.")

        # Validate the final value.
        if isinstance(val, list):
            for component in val:
                check_scalar_value(component)
            if inspect.isclass(member_type) and issubclass(member_type, Enum):
                if len(val) != len(set(val)):
                    raise ParseError(f"Duplicate enum values specified in list: {val}")
        elif isinstance(val, dict):
            for component in val.values():
                check_scalar_value(component)
        else:
            check_scalar_value(val)

        return val, Rank.from_pyo3_source(source)

    def _inverse_arg(self, arg: str) -> str | None:
        if not arg.startswith("--"):
            return None
        if arg.startswith("--no-"):
            raise BooleanOptionNameWithNo(self.scope, arg)
        return f"--no-{arg[2:]}"

    def _scope_str(self, scope: str | None = None) -> str:
        return self.scope_str(scope if scope is not None else self.scope)

    def __str__(self) -> str:
        return f"Parser({self._scope})"
