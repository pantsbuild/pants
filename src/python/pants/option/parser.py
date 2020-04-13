# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import copy
import inspect
import json
import os
import re
import traceback
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

import Levenshtein
import yaml

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import validate_deprecation_semver, warn_or_error
from pants.option.config import Config
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
    FromfileError,
    ImplicitValIsNone,
    InvalidKwarg,
    InvalidKwargNonGlobalScope,
    InvalidMemberType,
    MemberTypeNotAllowed,
    MutuallyExclusiveOptionError,
    NoOptionNames,
    OptionAlreadyRegistered,
    OptionNameDash,
    OptionNameDoubleDash,
    ParseError,
    RecursiveSubsystemOption,
    RegistrationError,
    Shadowing,
)
from pants.option.option_tracker import OptionTracker
from pants.option.option_util import flatten_shlexed_list, is_dict_option, is_list_option
from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION, ScopeInfo
from pants.util.meta import frozen_after_init


class Parser:
    """An argument parser in a hierarchy.

    Each node in the hierarchy is a 'scope': the root is the global scope, and the parent of
    a node is the scope it's immediately contained in. E.g., the 'compile.java' scope is
    a child of the 'compile' scope, which is a child of the global scope.

    Options registered on a parser are also registered transitively on all the scopes it encloses.
    We forbid registering options that shadow other options, and registration walks up and down the
    hierarchy to enforce that.
    """

    @staticmethod
    def _ensure_bool(val: Union[bool, str]) -> bool:
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
    def _invert(cls, s: Optional[Union[bool, str]]) -> Optional[bool]:
        if s is None:
            return None
        b = cls._ensure_bool(s)
        return not b

    @classmethod
    def scope_str(cls, scope: str) -> str:
        return "global scope" if scope == GLOBAL_SCOPE else f"scope '{scope}'"

    @classmethod
    def _check_shadowing(cls, parent_scope, parent_known_args, child_scope, child_known_args):
        for arg in parent_known_args & child_known_args:
            raise Shadowing(child_scope, arg, outer_scope=cls.scope_str(parent_scope))

    def __init__(
        self,
        env: Mapping[str, str],
        config: Config,
        scope_info: ScopeInfo,
        parent_parser: Optional["Parser"],
        option_tracker: OptionTracker,
    ) -> None:
        """Create a Parser instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param scope_info: the scope this parser acts for.
        :param parent_parser: the parser for the scope immediately enclosing this one, or
                              None if this is the global scope.
        :param option_tracker: the option tracker to record where option values came from.
        """
        self._env = env
        self._config = config
        self._scope_info = scope_info
        self._scope = self._scope_info.scope
        self._option_tracker = option_tracker

        # All option args registered with this parser.  Used to prevent shadowing args in inner scopes.
        self._known_args: Set[str] = set()

        # List of (args, kwargs) registration pairs, exactly as captured at registration time.
        self._option_registrations: List[Tuple[Tuple[str, ...], Dict[str, Any]]] = []

        self._parent_parser = parent_parser
        self._child_parsers: List["Parser"] = []

        if self._parent_parser:
            self._parent_parser._register_child_parser(self)

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def known_args(self) -> Set[str]:
        return self._known_args

    def walk(self, callback: Callable) -> None:
        """Invoke callback on this parser and its descendants, in depth-first order."""
        callback(self)
        for child in self._child_parsers:
            child.walk(callback)

    @frozen_after_init
    @dataclass(unsafe_hash=True)
    class ParseArgsRequest:
        flag_value_map: Dict
        namespace: OptionValueContainer
        get_all_scoped_flag_names: Callable[["Parser.ParseArgsRequest"], Iterable]
        levenshtein_max_distance: int
        # A passive option is one that doesn't affect functionality, or appear in help messages, but
        # can be provided without failing validation. This allows us to conditionally register options
        # (e.g., v1 only or v2 only) without having to remove usages when the condition changes.
        # TODO: This is currently only used for the v1/v2 switch. When everything is v2 we'll probably
        #  want to get rid of this concept.
        include_passive_options: bool

        def __init__(
            self,
            flags_in_scope: Iterable[str],
            namespace: OptionValueContainer,
            get_all_scoped_flag_names: Callable[[], Iterable],
            levenshtein_max_distance: int,
            include_passive_options: bool = False,
        ) -> None:
            """
            :param flags_in_scope: Iterable of arg strings to parse into flag values.
            :param namespace: The object to register the flag values on
            :param get_all_scoped_flag_names: A 0-argument function which returns an iterable of
                                              all registered option names in all their scopes. This
                                              is used to create an error message with suggestions
                                              when raising a `ParseError`.
            :param levenshtein_max_distance: The maximum Levenshtein edit distance between option names
                                             to determine similarly named options when an option name
                                             hasn't been registered.
            """
            self.flag_value_map = self._create_flag_value_map(flags_in_scope)
            self.namespace = namespace
            self.get_all_scoped_flag_names = get_all_scoped_flag_names  # type: ignore[assignment]  # cannot assign a method
            self.levenshtein_max_distance = levenshtein_max_distance
            self.include_passive_options = include_passive_options

        @staticmethod
        def _create_flag_value_map(flags: Iterable[str]) -> DefaultDict[str, List[Optional[str]]]:
            """Returns a map of flag -> list of values, based on the given flag strings.

            None signals no value given (e.g., -x, --foo). The value is a list because the user may
            specify the same flag multiple times, and that's sometimes OK (e.g., when appending to
            list- valued options).
            """
            flag_value_map: DefaultDict[str, List[Optional[str]]] = defaultdict(list)
            for flag in flags:
                flag_val: Optional[str]
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
        get_all_scoped_flag_names = parse_args_request.get_all_scoped_flag_names
        levenshtein_max_distance = parse_args_request.levenshtein_max_distance

        mutex_map: DefaultDict[str, List[str]] = defaultdict(list)
        for args, kwargs in self._unnormalized_option_registrations_iter():
            if kwargs.get("passive") and not parse_args_request.include_passive_options:
                continue

            self._validate(args, kwargs)
            name, dest = self.parse_name_and_dest(*args, **kwargs)

            # Compute the values provided on the command line for this option.  Note that there may be
            # multiple values, for any combination of the following reasons:
            #   - The user used the same flag multiple times.
            #   - The user specified a boolean flag (--foo) and its inverse (--no-foo).
            #   - The option has multiple names, and the user used more than one of them.
            #
            # We also check if the option is deprecated, but we only do so if the option is explicitly
            # specified as a command-line flag, so we don't spam users with deprecated option values
            # specified in config, which isn't something they control.
            implicit_value = kwargs.get("implicit_value")
            if implicit_value is None and kwargs.get("type") == bool:
                implicit_value = True  # Allows --foo to mean --foo=true.

            flag_vals: List[Union[int, float, bool, str]] = []

            def add_flag_val(v: Optional[Union[int, float, bool, str]]) -> None:
                if v is None:
                    if implicit_value is None:
                        raise ParseError(
                            f"Missing value for command line flag {arg} in {self._scope_str()}"
                        )
                    flag_vals.append(implicit_value)
                else:
                    flag_vals.append(v)

            for arg in args:
                # If the user specified --no-foo on the cmd line, treat it as if the user specified
                # --foo, but with the inverse value.
                if kwargs.get("type") == bool:
                    inverse_arg = self._inverse_arg(arg)
                    if inverse_arg in flag_value_map:
                        flag_value_map[arg] = [self._invert(v) for v in flag_value_map[inverse_arg]]
                        implicit_value = self._invert(implicit_value)
                        del flag_value_map[inverse_arg]

                if arg in flag_value_map:
                    for v in flag_value_map[arg]:
                        add_flag_val(v)
                    del flag_value_map[arg]

            # Get the value for this option, falling back to defaults as needed.
            try:
                val = self._compute_value(dest, kwargs, flag_vals)
            except ParseError as e:
                # Reraise a new exception with context on the option being processed at the time of error.
                # Note that other exception types can be raised here that are caught by ParseError (e.g.
                # BooleanConversionError), hence we reference the original exception type as type(e).
                raise type(e)(
                    "Error computing value for {} in {} (may also be from PANTS_* environment variables)."
                    "\nCaused by:\n{}".format(
                        ", ".join(args), self._scope_str(), traceback.format_exc()
                    )
                )

            # If the option is explicitly given, check deprecation and mutual exclusion.
            if val.rank > Rank.HARDCODED:
                self._check_deprecated(name, kwargs)

                mutex_dest = kwargs.get("mutually_exclusive_group")
                if mutex_dest:
                    mutex_map[mutex_dest].append(dest)
                    dest = mutex_dest
                else:
                    mutex_map[dest].append(dest)

                if len(mutex_map[dest]) > 1:
                    raise MutuallyExclusiveOptionError(
                        f"Can only provide one of the mutually exclusive options {mutex_map[dest]}"
                    )

            setattr(namespace, dest, val)

        # See if there are any unconsumed flags remaining, and if so, raise a ParseError.
        if flag_value_map:
            self._raise_error_for_invalid_flag_names(
                flag_value_map,
                all_scoped_flag_names=get_all_scoped_flag_names(),
                levenshtein_max_distance=levenshtein_max_distance,
            )

        return namespace

    def _raise_error_for_invalid_flag_names(
        self, flag_value_map, all_scoped_flag_names, levenshtein_max_distance
    ):
        """Identify similar option names to unconsumed flags and raise a ParseError with those
        names."""
        matching_flags = {}
        for flag_name in flag_value_map.keys():
            # We will be matching option names without their leading hyphens, in order to capture both
            # short and long-form options.
            flag_normalized_unscoped_name = re.sub(r"^-+", "", flag_name)
            flag_normalized_scoped_name = (
                f"{self.scope.replace('.', '-')}-{flag_normalized_unscoped_name}"
                if self.scope != GLOBAL_SCOPE
                else flag_normalized_unscoped_name
            )

            substring_matching_option_names = []
            levenshtein_matching_option_names = defaultdict(list)
            for other_scoped_flag in all_scoped_flag_names:
                other_complete_flag_name = other_scoped_flag.scoped_arg
                other_normalized_scoped_name = other_scoped_flag.normalized_scoped_arg
                other_normalized_unscoped_name = other_scoped_flag.normalized_arg
                if flag_normalized_unscoped_name == other_normalized_unscoped_name:
                    # If the unscoped option name itself matches, but the scope doesn't, display it.
                    substring_matching_option_names.append(other_complete_flag_name)
                elif other_normalized_scoped_name.startswith(flag_normalized_scoped_name):
                    # If the invalid scoped option name is the beginning of another scoped option name,
                    # display it. This will also suggest long-form options such as --verbose for an attempted
                    # -v (if -v isn't defined as an option).
                    substring_matching_option_names.append(other_complete_flag_name)
                else:
                    # If an unscoped option name is similar to the unscoped option from the command line
                    # according to --option-name-check-distance, display the matching scoped option name. This
                    # covers misspellings!
                    unscoped_option_levenshtein_distance = Levenshtein.distance(
                        flag_normalized_unscoped_name, other_normalized_unscoped_name
                    )
                    if unscoped_option_levenshtein_distance <= levenshtein_max_distance:
                        # NB: We order the matched flags by Levenshtein distance compared to the entire option string!
                        fully_scoped_levenshtein_distance = Levenshtein.distance(
                            flag_normalized_scoped_name, other_normalized_scoped_name
                        )
                        levenshtein_matching_option_names[fully_scoped_levenshtein_distance].append(
                            other_complete_flag_name
                        )

            # If any option name matched or started with the invalid flag in any scope, put that
            # first. Then, display the option names matching in order of overall edit distance, in a deterministic way.
            all_matching_scoped_option_names = substring_matching_option_names + [
                flag
                for distance in sorted(levenshtein_matching_option_names.keys())
                for flag in sorted(levenshtein_matching_option_names[distance])
            ]
            if all_matching_scoped_option_names:
                matching_flags[flag_name] = all_matching_scoped_option_names

        if matching_flags:
            suggestions_message = " Suggestions:\n{}".format(
                "\n".join(
                    "{}: [{}]".format(flag_name, ", ".join(matches))
                    for flag_name, matches in matching_flags.items()
                )
            )
        else:
            suggestions_message = ""
        raise ParseError(
            "Unrecognized command line flags on {scope}: {flags}.{suggestions_message}".format(
                scope=self._scope_str(),
                flags=", ".join(flag_value_map.keys()),
                suggestions_message=suggestions_message,
            )
        )

    def option_registrations_iter(self):
        """Returns an iterator over the normalized registration arguments of each option in this
        parser.

        Useful for generating help and other documentation.

        Each yielded item is an (args, kwargs) pair, as passed to register(), except that kwargs
        will be normalized in the following ways:
          - It will always have 'dest' explicitly set.
          - It will always have 'default' explicitly set, and the value will be a Rank.
          - For recursive options, the original registrar will also have 'recursive_root' set.

        Note that recursive options we inherit from a parent will also be yielded here, with
        the correctly-scoped default value.
        """

        def normalize_kwargs(args, orig_kwargs):
            nkwargs = copy.copy(orig_kwargs)
            _, dest = self.parse_name_and_dest(*args, **nkwargs)
            nkwargs["dest"] = dest
            if not ("default" in nkwargs and isinstance(nkwargs["default"], RankedValue)):
                nkwargs["default"] = self._compute_value(dest, nkwargs, [])
            return nkwargs

        # First yield any recursive options we inherit from our parent.
        if self._parent_parser:
            for args, kwargs in self._parent_parser._recursive_option_registration_args():
                yield args, normalize_kwargs(args, kwargs)

        # Then yield our directly-registered options.
        # This must come after yielding inherited recursive options, so we can detect shadowing.
        for args, kwargs in self._option_registrations:
            normalized_kwargs = normalize_kwargs(args, kwargs)
            if "recursive" in normalized_kwargs:
                # If we're the original registrar, make sure we can distinguish that.
                normalized_kwargs["recursive_root"] = True
            yield args, normalized_kwargs

    def _unnormalized_option_registrations_iter(self):
        """Returns an iterator over the raw registration arguments of each option in this parser.

        Each yielded item is an (args, kwargs) pair, exactly as passed to register(), except for
        substituting list and dict types with list_option/dict_option.

        Note that recursive options we inherit from a parent will also be yielded here.
        """
        # First yield any recursive options we inherit from our parent.
        if self._parent_parser:
            for args, kwargs in self._parent_parser._recursive_option_registration_args():
                yield args, kwargs
        # Then yield our directly-registered options.
        for args, kwargs in self._option_registrations:
            if "recursive" in kwargs and self._scope_info.category == ScopeInfo.SUBSYSTEM:
                raise RecursiveSubsystemOption(self.scope, args[0])
            yield args, kwargs

    def _recursive_option_registration_args(self):
        """Yield args, kwargs pairs for just our recursive options.

        Includes all the options we inherit recursively from our ancestors.
        """
        if self._parent_parser:
            for args, kwargs in self._parent_parser._recursive_option_registration_args():
                yield args, kwargs
        for args, kwargs in self._option_registrations:
            # Note that all subsystem options are implicitly recursive: a subscope of a subsystem
            # scope is another (optionable-specific) instance of the same subsystem, so it needs
            # all the same options.
            if self._scope_info.category == ScopeInfo.SUBSYSTEM or "recursive" in kwargs:
                yield args, kwargs

    def register(self, *args, **kwargs) -> None:
        """Register an option."""
        if args:
            name, dest = self.parse_name_and_dest(*args, **kwargs)
            self._check_deprecated(name, kwargs, print_warning=False)

        if kwargs.get("type") == bool:
            default = kwargs.get("default")
            if default is None:
                # Unless a tri-state bool is explicitly opted into with the `UnsetBool` default value,
                # boolean options always have an implicit boolean-typed default. We make that default
                # explicit here.
                kwargs["default"] = not self._ensure_bool(kwargs.get("implicit_value", True))
            elif default is UnsetBool:
                kwargs["default"] = None

        # Record the args. We'll do the underlying parsing on-demand.
        self._option_registrations.append((args, kwargs))

        # Look for shadowing options up and down the hierarchy.
        args_set = set(args)
        for parent in self._parents_transitive():
            self._check_shadowing(parent.scope, parent._known_args, self.scope, args_set)
        for child in self._children_transitive():
            self._check_shadowing(self.scope, args_set, child.scope, child._known_args)

        # And look for direct conflicts
        for arg in args:
            if arg in self._known_args:
                raise OptionAlreadyRegistered(self.scope, arg)
        self._known_args.update(args)

    def _check_deprecated(self, name: str, kwargs, print_warning: bool = True) -> None:
        """Checks option for deprecation and issues a warning/error if necessary."""
        removal_version = kwargs.get("removal_version", None)
        if removal_version is not None:
            warn_or_error(
                removal_version=removal_version,
                deprecated_entity_description=f"option '{name}' in {self._scope_str()}",
                deprecation_start_version=kwargs.get("deprecation_start_version", None),
                hint=kwargs.get("removal_hint", None),
                stacklevel=9999,  # Out of range stacklevel to suppress printing src line.
                print_warning=print_warning,
            )

    _allowed_registration_kwargs = {
        "type",
        "member_type",
        "choices",
        "dest",
        "default",
        "implicit_value",
        "metavar",
        "help",
        "advanced",
        "recursive",
        "recursive_root",
        "registering_class",
        "fingerprint",
        "removal_version",
        "removal_hint",
        "deprecation_start_version",
        "fromfile",
        "mutually_exclusive_group",
        "daemon",
        "passive",
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
            exception_type: Type[RegistrationError], arg_name: Optional[str] = None, **msg_kwargs,
        ) -> None:
            if arg_name is None:
                arg_name = args[0] if args else "<unknown>"
            raise exception_type(self.scope, arg_name, **msg_kwargs)

        if not args:
            error(NoOptionNames)
        # validate args.
        for arg in args:
            if not arg.startswith("-"):
                error(OptionNameDash, arg_name=arg)
            if not arg.startswith("--") and len(arg) > 2:
                error(OptionNameDoubleDash, arg_name=arg)

        # Validate kwargs.
        if "implicit_value" in kwargs and kwargs["implicit_value"] is None:
            error(ImplicitValIsNone)

        if "member_type" in kwargs and kwargs.get("type") != list:
            error(MemberTypeNotAllowed, type_=kwargs.get("type", str).__name__)

        if kwargs.get("member_type", str) not in self._allowed_member_types:
            error(InvalidMemberType, member_type=kwargs.get("member_type", str).__name__)

        for kwarg in kwargs:
            if kwarg not in self._allowed_registration_kwargs:
                error(InvalidKwarg, kwarg=kwarg)

            # Ensure `daemon=True` can't be passed on non-global scopes (except for `recursive=True`).
            if (
                kwarg == "daemon"
                and self._scope != GLOBAL_SCOPE
                and kwargs.get("recursive") is False
            ):
                error(InvalidKwargNonGlobalScope, kwarg=kwarg)

        removal_version = kwargs.get("removal_version")
        if removal_version is not None:
            validate_deprecation_semver(removal_version, "removal version")

    def _parents_transitive(self):
        ancestor = self._parent_parser
        while ancestor:
            yield ancestor
            ancestor = ancestor._parent_parser

    def _children_transitive(self):
        for child in self._child_parsers:
            yield child
            yield from child._children_transitive()

    _ENV_SANITIZER_RE = re.compile(r"[.-]")

    @staticmethod
    def parse_name_and_dest(*args, **kwargs):
        """Return the name and dest for an option registration.

        If an explicit `dest` is specified, returns that and otherwise derives a default from the
        option flags where '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.
        """
        arg = next((a for a in args if a.startswith("--")), args[0])
        name = arg.lstrip("-").replace("-", "_")

        dest = kwargs.get("dest")
        return name, dest if dest else name

    @staticmethod
    def _wrap_type(t):
        if t == list:
            return ListValueComponent.create
        if t == dict:
            return DictValueComponent.create
        return t

    @staticmethod
    def _convert_member_type(t, x):
        if t == dict:
            return DictValueComponent.create(x).val
        return t(x)

    def _compute_value(self, dest, kwargs, flag_val_strs):
        """Compute the value to use for an option.

        The source of the default value is chosen according to the ranking in Rank.
        """
        # Helper function to convert a string to a value of the option's type.
        def to_value_type(val_str):
            if val_str is None:
                return None
            type_arg = kwargs.get("type", str)
            if type_arg == bool:
                return self._ensure_bool(val_str)
            try:
                return self._wrap_type(type_arg)(val_str)
            except (TypeError, ValueError) as e:
                raise ParseError(
                    f"Error applying type '{type_arg.__name__}' to option value '{val_str}', for option "
                    f"'--{dest}' in {self._scope_str()}: {e}"
                )

        # Helper function to expand a fromfile=True value string, if needed.
        # May return a string or a dict/list decoded from a json/yaml file.
        def expand(val_or_str):
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
                        with open(fromfile, "r") as fp:
                            s = fp.read().strip()
                            if fromfile.endswith(".json"):
                                return json.loads(s)
                            elif fromfile.endswith(".yml") or fromfile.endswith(".yaml"):
                                return yaml.safe_load(s)
                            else:
                                return s
                    except (IOError, ValueError, yaml.YAMLError) as e:
                        raise FromfileError(
                            f"Failed to read {dest} in {self._scope_str()} from file {fromfile}: {e!r}"
                        )
            else:
                return val_or_str

        # Get value from config files, and capture details about its derivation.
        config_details = None
        config_section = GLOBAL_SCOPE_CONFIG_SECTION if self._scope == GLOBAL_SCOPE else self._scope
        config_default_val_or_str = expand(
            self._config.get(Config.DEFAULT_SECTION, dest, default=None)
        )
        config_val_or_str = expand(self._config.get(config_section, dest, default=None))
        config_source_file = self._config.get_source_for_option(
            config_section, dest
        ) or self._config.get_source_for_option(Config.DEFAULT_SECTION, dest)
        if config_source_file is not None:
            config_source_file = os.path.relpath(config_source_file)
            config_details = f"in {config_source_file}"

        # Get value from environment, and capture details about its derivation.
        udest = dest.upper()
        if self._scope == GLOBAL_SCOPE:
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
            sanitized_env_var_scope = self._ENV_SANITIZER_RE.sub("_", self._scope.upper())
            env_vars = [f"PANTS_{sanitized_env_var_scope}_{udest}"]

        env_val_or_str = None
        env_details = None
        if self._env:
            for env_var in env_vars:
                if env_var in self._env:
                    env_val_or_str = expand(self._env.get(env_var))
                    env_details = f"from env var {env_var}"
                    break

        # Get value from cmd-line flags.
        flag_vals = [to_value_type(expand(x)) for x in flag_val_strs]
        if is_list_option(kwargs):
            # Note: It's important to set flag_val to None if no flags were specified, so we can
            # distinguish between no flags set vs. explicit setting of the value to [].
            flag_val = ListValueComponent.merge(flag_vals) if flag_vals else None
        elif is_dict_option(kwargs):
            # Note: It's important to set flag_val to None if no flags were specified, so we can
            # distinguish between no flags set vs. explicit setting of the value to {}.
            flag_val = DictValueComponent.merge(flag_vals) if flag_vals else None
        elif len(flag_vals) > 1:
            raise ParseError(
                "Multiple cmd line flags specified for option {} in {}".format(
                    dest, self._scope_str()
                )
            )
        elif len(flag_vals) == 1:
            flag_val = flag_vals[0]
        else:
            flag_val = None

        # Rank all available values.
        # Note that some of these values may already be of the value type, but type conversion
        # is idempotent, so this is OK.

        values_to_rank = [
            to_value_type(x)
            for x in [
                flag_val,
                env_val_or_str,
                config_val_or_str,
                config_default_val_or_str,
                kwargs.get("default"),
                None,
            ]
        ]
        # Note that ranked_vals will always have at least one element, and all elements will be
        # instances of RankedValue (so none will be None, although they may wrap a None value).
        ranked_vals = list(reversed(list(RankedValue.prioritized_iter(*values_to_rank))))

        def record_option(value, rank, option_details=None):
            deprecation_version = kwargs.get("removal_version")
            self._option_tracker.record_option(
                scope=self._scope,
                option=dest,
                value=value,
                rank=rank,
                deprecation_version=deprecation_version,
                details=option_details,
            )

        # Record info about the derivation of each of the contributing values.
        detail_history = []
        for ranked_val in ranked_vals:
            if ranked_val.rank in (Rank.CONFIG, Rank.CONFIG_DEFAULT):
                details = config_details
            elif ranked_val.rank == Rank.ENVIRONMENT:
                details = env_details
            else:
                details = None
            if details:
                detail_history.append(details)
            record_option(value=ranked_val.value, rank=ranked_val.rank, option_details=details)

        # Helper function to check various validity constraints on final option values.
        def check(val):
            if val is None:
                return
            choices = kwargs.get("choices")
            type_arg = kwargs.get("type")
            if choices is None and "type" in kwargs:
                if inspect.isclass(type_arg) and issubclass(type_arg, Enum):
                    choices = list(type_arg)
            # TODO: convert this into an enum() pattern match!
            if choices is not None and val not in choices:
                raise ParseError(
                    "`{}` is not an allowed value for option {} in {}. "
                    "Must be one of: {}".format(val, dest, self._scope_str(), choices)
                )

            if type_arg == file_option:
                check_file_exists(val)
            if type_arg == dir_option:
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

        # Generate the final value from all available values, and check that it (or its members,
        # if a list) are in the set of allowed choices.
        if is_list_option(kwargs):
            merged_rank = ranked_vals[-1].rank
            merged_val = ListValueComponent.merge(
                [rv.value for rv in ranked_vals if rv.value is not None]
            ).val
            # TODO: run `check()` for all elements of a list option too!!!
            merged_val = [
                self._convert_member_type(kwargs.get("member_type", str), x) for x in merged_val
            ]
            if kwargs.get("member_type") == shell_str:
                merged_val = flatten_shlexed_list(merged_val)
            for val in merged_val:
                check(val)
            ret = RankedValue(merged_rank, merged_val)
        elif is_dict_option(kwargs):
            # TODO: convert `member_type` for dict values too!
            merged_rank = ranked_vals[-1].rank
            merged_val = DictValueComponent.merge(
                [rv.value for rv in ranked_vals if rv.value is not None]
            ).val
            for val in merged_val:
                check(val)
            ret = RankedValue(merged_rank, merged_val)
        else:
            ret = ranked_vals[-1]
            check(ret.value)

        # Record info about the derivation of the final value.
        merged_details = ", ".join(detail_history) if detail_history else None
        record_option(value=ret.value, rank=ret.rank, option_details=merged_details)

        # All done!
        return ret

    def _inverse_arg(self, arg: str) -> Optional[str]:
        if not arg.startswith("--"):
            return None
        if arg.startswith("--no-"):
            raise BooleanOptionNameWithNo(self.scope, arg)
        return f"--no-{arg[2:]}"

    def _register_child_parser(self, child: "Parser") -> None:
        self._child_parsers.append(child)

    def _scope_str(self, scope: Optional[str] = None) -> str:
        return self.scope_str(scope if scope is not None else self.scope)

    def __str__(self) -> str:
        return f"Parser({self._scope})"
