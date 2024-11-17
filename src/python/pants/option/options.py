# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import warn_or_error
from pants.option.arg_splitter import ArgSplitter
from pants.option.config import Config
from pants.option.errors import (
    ConfigValidationError,
    MutuallyExclusiveOptionError,
    UnknownFlagsError,
)
from pants.option.native_options import NativeOptionParser
from pants.option.option_util import is_list_option
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.ranked_value import Rank, RankedValue
from pants.option.registrar import OptionRegistrar
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION, ScopeInfo
from pants.util.memo import memoized_method
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class NativeOptionsValidation(Enum):
    ignore = "ignore"
    warning = "warning"
    error = "error"


class Options:
    """The outward-facing API for interacting with options.

    Supports option registration and fetching option values.

    Examples:

    The value in global scope of option '--foo-bar' (registered in global scope) will be selected
    in the following order:
      - The value of the --foo-bar flag in global scope.
      - The value of the PANTS_GLOBAL_FOO_BAR environment variable.
      - The value of the PANTS_FOO_BAR environment variable.
      - The value of the foo_bar key in the [GLOBAL] section of pants.toml.
      - The hard-coded value provided at registration time.
      - None.

    The value in scope 'compile.java' of option '--foo-bar' (registered in global scope) will be
    selected in the following order:
      - The value of the --foo-bar flag in scope 'compile.java'.
      - The value of the --foo-bar flag in scope 'compile'.
      - The value of the --foo-bar flag in global scope.
      - The value of the PANTS_COMPILE_JAVA_FOO_BAR environment variable.
      - The value of the PANTS_COMPILE_FOO_BAR environment variable.
      - The value of the PANTS_GLOBAL_FOO_BAR environment variable.
      - The value of the PANTS_FOO_BAR environment variable.
      - The value of the foo_bar key in the [compile.java] section of pants.toml.
      - The value of the foo_bar key in the [compile] section of pants.toml.
      - The value of the foo_bar key in the [GLOBAL] section of pants.toml.
      - The hard-coded value provided at registration time.
      - None.

    The value in scope 'compile.java' of option '--foo-bar' (registered in scope 'compile') will be
    selected in the following order:
      - The value of the --foo-bar flag in scope 'compile.java'.
      - The value of the --foo-bar flag in scope 'compile'.
      - The value of the PANTS_COMPILE_JAVA_FOO_BAR environment variable.
      - The value of the PANTS_COMPILE_FOO_BAR environment variable.
      - The value of the foo_bar key in the [compile.java] section of pants.toml.
      - The value of the foo_bar key in the [compile] section of pants.toml.
      - The value of the foo_bar key in the [GLOBAL] section of pants.toml
        (because of automatic config file fallback to that section).
      - The hard-coded value provided at registration time.
      - None.
    """

    class DuplicateScopeError(Exception):
        """More than one registration occurred for the same scope."""

    class AmbiguousPassthroughError(Exception):
        """More than one goal was passed along with passthrough args."""

    @classmethod
    def complete_scopes(cls, scope_infos: Iterable[ScopeInfo]) -> FrozenOrderedSet[ScopeInfo]:
        """Expand a set of scopes to include scopes they deprecate.

        Also validates that scopes do not collide.
        """
        ret: OrderedSet[ScopeInfo] = OrderedSet()
        original_scopes: dict[str, ScopeInfo] = {}
        for si in sorted(scope_infos, key=lambda _si: _si.scope):
            if si.scope in original_scopes:
                raise cls.DuplicateScopeError(
                    softwrap(
                        f"""
                        Scope `{si.scope}` claimed by {si}, was also claimed
                        by {original_scopes[si.scope]}.
                        """
                    )
                )
            original_scopes[si.scope] = si
            ret.add(si)
            if si.deprecated_scope:
                ret.add(dataclasses.replace(si, scope=si.deprecated_scope))
                original_scopes[si.deprecated_scope] = si
        return FrozenOrderedSet(ret)

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        config: Config,
        known_scope_infos: Iterable[ScopeInfo],
        args: Sequence[str],
        bootstrap_option_values: OptionValueContainer | None = None,
        allow_unknown_options: bool = False,
        native_options_config_discovery: bool = True,
        include_derivation: bool = False,
    ) -> Options:
        """Create an Options instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
        :param args: a list of cmd-line args; defaults to `sys.argv` if None is supplied.
        :param bootstrap_option_values: An optional namespace containing the values of bootstrap
               options. We can use these values when registering other options.
        :param allow_unknown_options: Whether to ignore or error on unknown cmd-line flags.
        :param native_options_config_discovery: Whether to discover config files in the native
            parser or use the ones supplied.
        :param include_derivation: Whether to gather option value derivation information.
        """
        # We need registrars for all the intermediate scopes, so inherited option values
        # can propagate through them.
        complete_known_scope_infos = cls.complete_scopes(known_scope_infos)
        splitter = ArgSplitter(complete_known_scope_infos, get_buildroot())
        split_args = splitter.split_args(args)

        if split_args.passthru and len(split_args.goals) > 1:
            raise cls.AmbiguousPassthroughError(
                softwrap(
                    f"""
                    Specifying multiple goals (in this case: {split_args.goals})
                    along with passthrough args (args after `--`) is ambiguous.

                    Try either specifying only a single goal, or passing the passthrough args
                    directly to the relevant consumer via its associated flags.
                    """
                )
            )

        if bootstrap_option_values:
            spec_files = bootstrap_option_values.spec_files
            if spec_files:
                for spec_file in spec_files:
                    with open(spec_file) as f:
                        split_args.specs.extend(
                            [line for line in [line.strip() for line in f] if line]
                        )

        registrar_by_scope = {
            si.scope: OptionRegistrar(si.scope) for si in complete_known_scope_infos
        }
        known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}

        config_to_pass = None if native_options_config_discovery else config.sources()

        native_parser = NativeOptionParser(
            args,
            env,
            config_sources=config_to_pass,
            allow_pantsrc=True,
            include_derivation=include_derivation,
        )

        return cls(
            builtin_or_auxiliary_goal=split_args.builtin_or_auxiliary_goal,
            goals=split_args.goals,
            unknown_goals=split_args.unknown_goals,
            scope_to_flags=split_args.scope_to_flags,
            specs=split_args.specs,
            passthru=split_args.passthru,
            registrar_by_scope=registrar_by_scope,
            native_parser=native_parser,
            bootstrap_option_values=bootstrap_option_values,
            known_scope_to_info=known_scope_to_info,
            allow_unknown_options=allow_unknown_options,
        )

    def __init__(
        self,
        builtin_or_auxiliary_goal: str | None,
        goals: list[str],
        unknown_goals: list[str],
        scope_to_flags: dict[str, list[str]],
        specs: list[str],
        passthru: list[str],
        registrar_by_scope: dict[str, OptionRegistrar],
        native_parser: NativeOptionParser,
        bootstrap_option_values: OptionValueContainer | None,
        known_scope_to_info: dict[str, ScopeInfo],
        allow_unknown_options: bool = False,
    ) -> None:
        """The low-level constructor for an Options instance.

        Dependents should use `Options.create` instead.
        """
        self._builtin_or_auxiliary_goal = builtin_or_auxiliary_goal
        self._goals = goals
        self._unknown_goals = unknown_goals
        self._scope_to_flags = scope_to_flags
        self._specs = specs
        self._passthru = passthru
        self._registrar_by_scope = registrar_by_scope
        self._native_parser = native_parser
        self._bootstrap_option_values = bootstrap_option_values
        self._known_scope_to_info = known_scope_to_info
        self._allow_unknown_options = allow_unknown_options

    @property
    def native_parser(self) -> NativeOptionParser:
        return self._native_parser

    @property
    def specs(self) -> list[str]:
        """The specifications to operate on, e.g. the target addresses and the file names.

        :API: public
        """
        return self._specs

    @property
    def builtin_or_auxiliary_goal(self) -> str | None:
        """The requested builtin or auxiliary goal, if any.

        :API: public
        """
        return self._builtin_or_auxiliary_goal

    @property
    def goals(self) -> list[str]:
        """The requested goals, in the order specified on the cmd line.

        :API: public
        """
        return self._goals

    @property
    def unknown_goals(self) -> list[str]:
        """The requested goals without implementation, in the order specified on the cmd line.

        :API: public
        """
        return self._unknown_goals

    @property
    def known_scope_to_info(self) -> dict[str, ScopeInfo]:
        return self._known_scope_to_info

    @property
    def known_scope_to_scoped_args(self) -> dict[str, frozenset[str]]:
        return {
            scope: registrar.known_scoped_args
            for scope, registrar in self._registrar_by_scope.items()
        }

    @property
    def scope_to_flags(self) -> dict[str, list[str]]:
        return self._scope_to_flags

    def verify_configs(self, global_config: Config) -> None:
        """Verify all loaded configs have correct scopes and options."""

        section_to_valid_options = {}
        for scope in self.known_scope_to_info:
            section = GLOBAL_SCOPE_CONFIG_SECTION if scope == GLOBAL_SCOPE else scope
            section_to_valid_options[section] = set(self.for_scope(scope, check_deprecations=False))
        global_config.verify(section_to_valid_options)

    def verify_args(self):
        # Consume all known args, and see if any are left.
        # This will have the side-effect of precomputing (and memoizing) options for all scopes.
        for scope in self.known_scope_to_info:
            self.for_scope(scope)
        # We implement some global help flags, such as `-h`, `--help`, '-v', `--version`,
        # as scope aliases (so `--help` is an alias for `help` and so on).
        # There aren't consumed by the native parser, since they aren't registered as options,
        # so we must account for them.
        scope_aliases_that_look_like_flags = set()
        for si in self.known_scope_to_info.values():
            scope_aliases_that_look_like_flags.update(
                sa for sa in si.scope_aliases if sa.startswith("-")
            )

        for scope, flags in self._native_parser.get_unconsumed_flags().items():
            flags = tuple(flag for flag in flags if flag not in scope_aliases_that_look_like_flags)
            if flags:
                # We may have unconsumed flags in multiple positional contexts, but our
                # error handling expects just one, so pick the first one. After the user
                # fixes that error we will show the next scope.
                raise UnknownFlagsError(flags, scope)

    def is_known_scope(self, scope: str) -> bool:
        """Whether the given scope is known by this instance.

        :API: public
        """
        return scope in self._known_scope_to_info

    def register(self, scope: str, *args, **kwargs) -> None:
        """Register an option in the given scope."""
        self.get_registrar(scope).register(*args, **kwargs)
        deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
        if deprecated_scope:
            self.get_registrar(deprecated_scope).register(*args, **kwargs)

    def registration_function_for_subsystem(self, subsystem_cls):
        """Returns a function for registering options on the given scope."""

        # TODO(benjy): Make this an instance of a class that implements __call__, so we can
        # docstring it, and so it's less weird than attaching properties to a function.
        def register(*args, **kwargs):
            self.register(subsystem_cls.options_scope, *args, **kwargs)

        # Clients can access the bootstrap option values as register.bootstrap.
        register.bootstrap = self.bootstrap_option_values()
        # Clients can access the scope as register.scope.
        register.scope = subsystem_cls.options_scope
        return register

    def get_registrar(self, scope: str) -> OptionRegistrar:
        """Returns the registrar for the given scope, so code can register on it directly.

        :param scope: The scope to retrieve the registrar for.
        :return: The registrar for the given scope.
        :raises pants.option.errors.ConfigValidationError: if the scope is not known.
        """
        try:
            return self._registrar_by_scope[scope]
        except KeyError:
            raise ConfigValidationError(f"No such options scope: {scope}")

    def _check_and_apply_deprecations(self, scope, values):
        """Checks whether a ScopeInfo has options specified in a deprecated scope.

        There are two related cases here. Either:
          1) The ScopeInfo has an associated deprecated_scope that was replaced with a non-deprecated
             scope, meaning that the options temporarily live in two locations.
          2) The entire ScopeInfo is deprecated (as in the case of deprecated SubsystemDependencies),
             meaning that the options live in one location.

        In the first case, this method has the side effect of merging options values from deprecated
        scopes into the given values.
        """
        si = self.known_scope_to_info[scope]

        # If this Scope is itself deprecated, report that.
        if si.removal_version:
            explicit_keys = self.for_scope(scope, check_deprecations=False).get_explicit_keys()
            if explicit_keys:
                warn_or_error(
                    removal_version=si.removal_version,
                    entity=f"scope {scope}",
                    hint=si.removal_hint,
                )

        # Check if we're the new name of a deprecated scope, and clone values from that scope.
        # Note that deprecated_scope and scope share the same Subsystem class, so deprecated_scope's
        # Subsystem has a deprecated_options_scope equal to deprecated_scope. Therefore we must
        # check that scope != deprecated_scope to prevent infinite recursion.
        deprecated_scope = si.deprecated_scope
        if deprecated_scope is not None and scope != deprecated_scope:
            # Do the deprecation check only on keys that were explicitly set
            # on the deprecated scope.
            explicit_keys = self.for_scope(
                deprecated_scope, check_deprecations=False
            ).get_explicit_keys()
            if explicit_keys:
                # Update our values with those of the deprecated scope.
                # Note that a deprecated val will take precedence over a val of equal rank.
                # This makes the code a bit neater.
                values.update(self.for_scope(deprecated_scope))

                warn_or_error(
                    removal_version=self.known_scope_to_info[
                        scope
                    ].deprecated_scope_removal_version,
                    entity=f"scope {deprecated_scope}",
                    hint=f"Use scope {scope} instead (options: {', '.join(explicit_keys)})",
                )

    # TODO: Eagerly precompute backing data for this?
    @memoized_method
    def for_scope(
        self,
        scope: str,
        check_deprecations: bool = True,
    ) -> OptionValueContainer:
        """Return the option values for the given scope.

        Values are attributes of the returned object, e.g., options.foo.
        Computed lazily per scope.

        :API: public
        :param scope: The scope to get options for.
        :param check_deprecations: Whether to check for any deprecations conditions.
        :return: An OptionValueContainer representing the option values for the given scope.
        :raises pants.option.errors.ConfigValidationError: if the scope is unknown.
        """
        builder = OptionValueContainerBuilder()
        mutex_map = defaultdict(list)
        registrar = self.get_registrar(scope)
        scope_str = "global scope" if scope == GLOBAL_SCOPE else f"scope '{scope}'"

        for args, kwargs in registrar.option_registrations_iter():
            dest = kwargs["dest"]
            val, rank = self._native_parser.get_value(
                scope=scope, registration_args=args, registration_kwargs=kwargs
            )
            explicitly_set = rank > Rank.HARDCODED

            # If we explicitly set a deprecated but not-yet-expired option, warn about it.
            # Otherwise, raise a CodeRemovedError if the deprecation has expired.
            removal_version = kwargs.get("removal_version", None)
            if removal_version is not None:
                warn_or_error(
                    removal_version=removal_version,
                    entity=f"option '{dest}' in {scope_str}",
                    start_version=kwargs.get("deprecation_start_version", None),
                    hint=kwargs.get("removal_hint", None),
                    print_warning=explicitly_set,
                )

            # If we explicitly set the option, check for mutual exclusivity.
            if explicitly_set:
                mutex_dest = kwargs.get("mutually_exclusive_group")
                mutex_map_key = mutex_dest or dest
                mutex_map[mutex_map_key].append(dest)
                if len(mutex_map[mutex_map_key]) > 1:
                    raise MutuallyExclusiveOptionError(
                        softwrap(
                            f"""
                            Can only provide one of these mutually exclusive options in
                            {scope_str}, but multiple given:
                            {', '.join(mutex_map[mutex_map_key])}
                            """
                        )
                    )
            setattr(builder, dest, RankedValue(rank, val))
        native_values = builder.build()

        # Check for any deprecation conditions, which are evaluated using `self._flag_matchers`.
        if check_deprecations:
            native_values_builder = native_values.to_builder()
            self._check_and_apply_deprecations(scope, native_values_builder)
            native_values = native_values_builder.build()
        return native_values

    def get_fingerprintable_for_scope(
        self,
        scope: str,
        daemon_only: bool = False,
    ) -> list[tuple[str, type, Any]]:
        """Returns a list of fingerprintable (option name, option type, option value) pairs for the
        given scope.

        Options are fingerprintable by default, but may be registered with "fingerprint=False".

        This method also searches enclosing options scopes of `bottom_scope` to determine the set of
        fingerprintable pairs.

        :param scope: The scope to gather fingerprintable options for.
        :param daemon_only: If true, only look at daemon=True options.
        """

        pairs = []
        registrar = self.get_registrar(scope)
        # Sort the arguments, so that the fingerprint is consistent.
        for _, kwargs in sorted(registrar.option_registrations_iter()):
            if not kwargs.get("fingerprint", True):
                continue
            if daemon_only and not kwargs.get("daemon", False):
                continue
            dest = kwargs["dest"]
            val = self.for_scope(scope)[dest]
            # If we have a list then we delegate to the fingerprinting implementation of the members.
            if is_list_option(kwargs):
                val_type = kwargs.get("member_type", str)
            else:
                val_type = kwargs.get("type", str)
            pairs.append((dest, val_type, val))
        return pairs

    def __getitem__(self, scope: str) -> OptionValueContainer:
        # TODO(John Sirois): Mainly supports use of dict<str, dict<str, str>> for mock options in tests,
        # Consider killing if tests consolidate on using TestOptions instead of the raw dicts.
        return self.for_scope(scope)

    def bootstrap_option_values(self) -> OptionValueContainer | None:
        """Return the option values for bootstrap options.

        General code can also access these values in the global scope.  But option registration code
        cannot, hence this special-casing of this small set of options.
        """
        return self._bootstrap_option_values

    def for_global_scope(self) -> OptionValueContainer:
        """Return the option values for the global scope.

        :API: public
        """
        return self.for_scope(GLOBAL_SCOPE)
