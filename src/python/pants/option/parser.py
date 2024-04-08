# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import copy
import inspect
import json
import logging
import re
import typing
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, DefaultDict, Iterable, Mapping

import yaml

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import validate_deprecation_semver, warn_or_error
from pants.option.config import DEFAULT_SECTION, Config
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
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.ranked_value import Rank, RankedValue
from pants.option.rust_options import NativeOptionParser
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION, ScopeInfo
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptionValueHistory:
    ranked_values: tuple[RankedValue]

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
        env: Mapping[str, str],
        config: Config,
        scope_info: ScopeInfo,
    ) -> None:
        """Create a Parser instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param scope_info: the scope this parser acts for.
        """
        self._env = env
        self._config = config
        self._scope_info = scope_info
        self._scope = self._scope_info.scope

        # All option args registered with this parser.  Used to prevent conflicts.
        self._known_args: set[str] = set()

        # List of (args, kwargs) registration pairs, exactly as captured at registration time.
        self._option_registrations: list[tuple[tuple[str, ...], dict[str, Any]]] = []

        # Map of dest -> history.
        self._history: dict[str, OptionValueHistory] = {}

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

    def history(self, dest: str) -> OptionValueHistory | None:
        return self._history.get(dest)

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
                        flag_val = None
                flag_value_map[key].append(flag_val)
            return flag_value_map

    def parse_args_native(self, native_parser: NativeOptionParser) -> OptionValueContainer:
        namespace = OptionValueContainerBuilder()
        for args, kwargs in self._option_registrations:
            self._validate(args, kwargs)
            dest = self.parse_dest(*args, **kwargs)
            val = native_parser.get(
                scope=self.scope,
                flags=args,
                default=kwargs.get("default"),
                option_type=kwargs.get("type"),
                member_type=kwargs.get("member_type"),
                passthrough=kwargs.get("passthrough"),
            )
            # TODO: If the option is explicitly given, check deprecation and mutual exclusion.
            setattr(namespace, dest, RankedValue(Rank.HARDCODED, val))
        return namespace.build()

    def parse_args(
        self, parse_args_request: ParseArgsRequest, log_warnings: bool = False
    ) -> OptionValueContainer:
        """Set values for this parser's options on the namespace object.

        :raises: :class:`ParseError` if any flags weren't recognized.
        """

        flag_value_map = parse_args_request.flag_value_map
        namespace = parse_args_request.namespace

        mutex_map: DefaultDict[str, list[str]] = defaultdict(list)
        for args, kwargs in self._option_registrations:
            self._validate(args, kwargs)
            dest = self.parse_dest(*args, **kwargs)

            # Compute the values provided on the command line for this option.  Note that there may be
            # multiple values, for any combination of the following reasons:
            #   - The user used the same flag multiple times.
            #   - The user specified a boolean flag (--foo) and its inverse (--no-foo).
            #   - The option has multiple names, and the user used more than one of them.
            #
            # We also check if the option is deprecated, but we only do so if the option is explicitly
            # specified as a command-line flag, so we don't spam users with deprecated option values
            # specified in config, which isn't something they control.
            flag_vals: list[int | float | bool | str] = []

            for arg in args:
                if self.is_bool(kwargs):
                    vals = flag_value_map.get(arg)
                    if vals:
                        # Ensure that --foo is as-if --foo-true.
                        vals[:] = [True if v is None else v for v in vals]
                    # If the user specified --no-foo on the cmd line, treat it as if the user specified
                    # --foo, but with the inverse value (ensuring that --no-foo is as-if --no-foo=true,
                    # which is as-if --foo=false).
                    inverse_arg = self._inverse_arg(arg)
                    if inverse_arg in flag_value_map:
                        flag_value_map[arg] = [
                            self._invert(v) or False for v in flag_value_map[inverse_arg]
                        ]
                        del flag_value_map[inverse_arg]

                if arg in flag_value_map:
                    for v in flag_value_map[arg]:
                        if v is None:
                            raise ParseError(
                                f"Missing value for command line flag {arg} in {self._scope_str()}"
                            )
                        flag_vals.append(v)
                    del flag_value_map[arg]

            # Get the value for this option, falling back to defaults as needed.
            try:
                value_history = self._compute_value(
                    dest,
                    kwargs,
                    flag_vals,
                    parse_args_request.passthrough_args,
                    log_warnings,
                )
                self._history[dest] = value_history
                val = value_history.final_value
            except ParseError as e:
                # Reraise a new exception with context on the option being processed at the time of error.
                # Note that other exception types can be raised here that are caught by ParseError (e.g.
                # BooleanConversionError), hence we reference the original exception type as type(e).
                args_str = ", ".join(args)
                raise type(e)(
                    softwrap(
                        f"""
                        Error computing value for {args_str} in {self._scope_str()} (may also be
                        from PANTS_* environment variables). Caused by:

                        {e}
                        """
                    )
                )

            # If the option is explicitly given, check deprecation and mutual exclusion.
            if val.rank > Rank.HARDCODED:
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

            setattr(namespace, dest, val)

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
                # boolean options always have an implicit default of False. We make that explicit here.
                kwargs["default"] = False
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

    def _compute_value(self, dest, kwargs, flag_val_strs, passthru_arg_strs, log_warnings):
        """Compute the value to use for an option.

        The source of the value is chosen according to the ranking in Rank.
        """
        type_arg = kwargs.get("type", str)
        member_type = kwargs.get("member_type", str)

        def to_value_type(val_str):
            return self.to_value_type(val_str, type_arg, member_type)

        # Helper function to expand a fromfile=True value string, if needed.
        # May return a string or a dict/list decoded from a json/yaml file.
        # If the fromfile is optional and the file does not exist then
        # None will be returned.
        def expand(val_or_str):
            if (
                kwargs.get("fromfile", True)
                and isinstance(val_or_str, str)
                and val_or_str.startswith("@")
            ):
                if val_or_str.startswith("@@"):  # Support a literal @ for fromfile values via @@.
                    return val_or_str[1:]
                else:
                    if val_or_str.startswith("@?"):  # Support an optional fromfile value via @?.
                        fromfile, optional = val_or_str[2:], True
                    else:
                        fromfile, optional = val_or_str[1:], False
                    fromfile_path = Path(get_buildroot(), fromfile)
                    try:
                        if optional and not fromfile_path.exists():
                            if log_warnings:
                                logger.warning(f"Optional file config {fromfile!r} does not exist.")
                            return None
                        contents = fromfile_path.read_text()
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

        # Helper function to merge multiple values from a single rank (e.g., multiple flags,
        # or multiple config files).
        def merge_in_rank(vals):
            if not vals:
                return None
            expanded_vals = [to_value_type(v) for v in (expand(i) for i in vals) if v is not None]
            if not expanded_vals:
                return None
            if is_list_option(kwargs):
                return ListValueComponent.merge(expanded_vals)
            if is_dict_option(kwargs):
                return DictValueComponent.merge(expanded_vals)
            return expanded_vals[-1]  # Last value wins.

        # Get value from config files, and capture details about its derivation.
        config_details = None
        config_section = GLOBAL_SCOPE_CONFIG_SECTION if self._scope == GLOBAL_SCOPE else self._scope
        config_default_val = merge_in_rank(self._config.get(DEFAULT_SECTION, dest))
        config_val = merge_in_rank(self._config.get(config_section, dest))
        config_source_files = self._config.get_sources_for_option(config_section, dest)
        if config_source_files:
            config_details = f"from {', '.join(config_source_files)}"

        # Get value from environment, and capture details about its derivation.
        env_vars = self.get_env_var_names(self._scope, dest)
        env_val = None
        env_details = None
        if self._env:
            for env_var in env_vars:
                if env_var in self._env:
                    env_val = merge_in_rank([self._env.get(env_var)])
                    env_details = f"from env var {env_var}"
                    break

        # Get value from cmd-line flags.
        flag_vals = list(flag_val_strs)
        if kwargs.get("passthrough") and passthru_arg_strs:
            # NB: Passthrough arguments are either of type `str` or `shell_str`
            # (see self._validate): the former never need interpretation, and the latter do not
            # need interpretation when they have been provided directly via `sys.argv` as the
            # passthrough args have been.
            flag_vals.append(
                ListValueComponent(ListValueComponent.MODIFY, [*passthru_arg_strs], [])
            )
        if len(flag_vals) > 1 and not (is_list_option(kwargs) or is_dict_option(kwargs)):
            raise ParseError(
                f"Multiple cmd line flags specified for option {dest} in {self._scope_str()}"
            )
        flag_val = merge_in_rank(flag_vals)
        flag_details = None if flag_val is None else "from command-line flag"

        # Rank all available values.
        values_to_rank = [
            (flag_val, flag_details),
            (env_val, env_details),
            (config_val, config_details),
            (config_default_val, config_details),
            (to_value_type(kwargs.get("default")), None),
            (None, None),
        ]
        # Note that ranked_vals will always have at least one element, and all elements will be
        # instances of RankedValue (so none will be None, although they may wrap a None value).
        ranked_vals = list(reversed(list(RankedValue.prioritized_iter(*values_to_rank))))

        def group(value_component_type, process_val_func) -> list[RankedValue]:
            # We group any values that are merged together, so that the history can reflect
            # merges vs. replacements in a useful way. E.g., if we merge [a, b] and [c],
            # and then replace it with [d, e], the history will contain:
            #   - [d, e] (from command-line flag)
            #   - [a, b, c] (from env var, from config)
            # And similarly for dicts.
            grouped: list[list[RankedValue]] = [[]]
            for ranked_val in ranked_vals:
                if ranked_val.value and ranked_val.value.action == value_component_type.REPLACE:
                    grouped.append([])
                grouped[-1].append(ranked_val)
            return [
                RankedValue(
                    grp[-1].rank,
                    process_val_func(
                        value_component_type.merge(
                            rv.value for rv in grp if rv.value is not None
                        ).val
                    ),
                    ", ".join(rv.details for rv in grp if rv.details),
                )
                for grp in grouped
                if grp
            ]

        if is_list_option(kwargs):

            def process_list(lst):
                return [self._convert_member_type(member_type, val) for val in lst]

            historic_ranked_vals = group(ListValueComponent, process_list)
        elif is_dict_option(kwargs):
            historic_ranked_vals = group(DictValueComponent, lambda x: x)
        else:
            historic_ranked_vals = ranked_vals

        value_history = OptionValueHistory(tuple(historic_ranked_vals))

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
        final_val = value_history.final_value
        if isinstance(final_val.value, list):
            for component in final_val.value:
                check_scalar_value(component)
            if inspect.isclass(member_type) and issubclass(member_type, Enum):
                if len(final_val.value) != len(set(final_val.value)):
                    raise ParseError(f"Duplicate enum values specified in list: {final_val.value}")
        elif isinstance(final_val.value, dict):
            for component in final_val.value.values():
                check_scalar_value(component)
        else:
            check_scalar_value(final_val.value)

        return value_history

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
