# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import warn_or_error
from pants.option.arg_splitter import ArgSplitter
from pants.option.config import Config
from pants.option.errors import ConfigValidationError
from pants.option.native_options import NativeOptionParser
from pants.option.option_util import is_list_option
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.parser import Parser
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
        # We default to error to be strict in tests, but set explicitly in OptionsBootstrapper
        # for user-facing behavior.
        native_options_validation: NativeOptionsValidation = NativeOptionsValidation.error,
    ) -> Options:
        """Create an Options instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
        :param args: a list of cmd-line args; defaults to `sys.argv` if None is supplied.
        :param bootstrap_option_values: An optional namespace containing the values of bootstrap
               options. We can use these values when registering other options.
        :param allow_unknown_options: Whether to ignore or error on unknown cmd-line flags.
        :param native_options_validation: How to validate the native options parser against the
               legacy Python parser.
        """
        # We need parsers for all the intermediate scopes, so inherited option values
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

        parser_by_scope = {si.scope: Parser(env, config, si) for si in complete_known_scope_infos}
        known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}

        native_parser = NativeOptionParser(args, env, config_sources=None, allow_pantsrc=True)

        return cls(
            builtin_goal=split_args.builtin_goal,
            goals=split_args.goals,
            unknown_goals=split_args.unknown_goals,
            scope_to_flags=split_args.scope_to_flags,
            specs=split_args.specs,
            passthru=split_args.passthru,
            parser_by_scope=parser_by_scope,
            native_parser=native_parser,
            native_options_validation=native_options_validation,
            bootstrap_option_values=bootstrap_option_values,
            known_scope_to_info=known_scope_to_info,
            allow_unknown_options=allow_unknown_options,
        )

    def __init__(
        self,
        builtin_goal: str | None,
        goals: list[str],
        unknown_goals: list[str],
        scope_to_flags: dict[str, list[str]],
        specs: list[str],
        passthru: list[str],
        parser_by_scope: dict[str, Parser],
        native_parser: NativeOptionParser,
        native_options_validation: NativeOptionsValidation,
        bootstrap_option_values: OptionValueContainer | None,
        known_scope_to_info: dict[str, ScopeInfo],
        allow_unknown_options: bool = False,
    ) -> None:
        """The low-level constructor for an Options instance.

        Dependents should use `Options.create` instead.
        """
        self._builtin_goal = builtin_goal
        self._goals = goals
        self._unknown_goals = unknown_goals
        self._scope_to_flags = scope_to_flags
        self._specs = specs
        self._passthru = passthru
        self._parser_by_scope = parser_by_scope
        self._native_parser = native_parser
        self._native_options_validation = native_options_validation
        self._bootstrap_option_values = bootstrap_option_values
        self._known_scope_to_info = known_scope_to_info
        self._allow_unknown_options = allow_unknown_options

    @property
    def specs(self) -> list[str]:
        """The specifications to operate on, e.g. the target addresses and the file names.

        :API: public
        """
        return self._specs

    @property
    def builtin_goal(self) -> str | None:
        """The requested builtin goal, if any.

        :API: public
        """
        return self._builtin_goal

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
        return {scope: parser.known_scoped_args for scope, parser in self._parser_by_scope.items()}

    @property
    def scope_to_flags(self) -> dict[str, list[str]]:
        return self._scope_to_flags

    def verify_configs(self, global_config: Config) -> None:
        """Verify all loaded configs have correct scopes and options."""

        section_to_valid_options = {}
        for scope in self.known_scope_to_info:
            section = GLOBAL_SCOPE_CONFIG_SECTION if scope == GLOBAL_SCOPE else scope
            section_to_valid_options[section] = set(
                self.for_scope(scope, check_deprecations=False, log_parser_warnings=True)
            )
        global_config.verify(section_to_valid_options)

    def is_known_scope(self, scope: str) -> bool:
        """Whether the given scope is known by this instance.

        :API: public
        """
        return scope in self._known_scope_to_info

    def register(self, scope: str, *args, **kwargs) -> None:
        """Register an option in the given scope."""
        self.get_parser(scope).register(*args, **kwargs)
        deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
        if deprecated_scope:
            self.get_parser(deprecated_scope).register(*args, **kwargs)

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

    def get_parser(self, scope: str) -> Parser:
        """Returns the parser for the given scope, so code can register on it directly.

        :param scope: The scope to retrieve the parser for.
        :return: The parser for the given scope.
        :raises pants.option.errors.ConfigValidationError: if the scope is not known.
        """
        try:
            return self._parser_by_scope[scope]
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

    def _make_parse_args_request(
        self, flags_in_scope, namespace: OptionValueContainerBuilder
    ) -> Parser.ParseArgsRequest:
        return Parser.ParseArgsRequest(
            flags_in_scope=flags_in_scope,
            namespace=namespace,
            passthrough_args=self._passthru,
            allow_unknown_flags=self._allow_unknown_options,
        )

    # TODO: Eagerly precompute backing data for this?
    @memoized_method
    def for_scope(
        self, scope: str, check_deprecations: bool = True, log_parser_warnings: bool = False
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

        values_builder = OptionValueContainerBuilder()
        flags_in_scope = self._scope_to_flags.get(scope, [])
        parse_args_request = self._make_parse_args_request(flags_in_scope, values_builder)
        legacy_values = self.get_parser(scope).parse_args(
            parse_args_request, log_warnings=log_parser_warnings
        )

        if self._native_options_validation == NativeOptionsValidation.ignore:
            native_values = None
        else:
            native_values = self.get_parser(scope).parse_args_native(self._native_parser)

        # Check for any deprecation conditions, which are evaluated using `self._flag_matchers`.
        if check_deprecations:
            values_builder = legacy_values.to_builder()
            self._check_and_apply_deprecations(scope, values_builder)
            legacy_values = values_builder.build()

            if native_values:
                native_values_builder = native_values.to_builder()
                self._check_and_apply_deprecations(scope, native_values_builder)
                native_values = native_values_builder.build()

        def listify_tuples(x):
            # Sequence values from the legacy parser can be tuple or list, but those coming from
            # the native parser are always list. We convert to list here for comparison purposes.
            if isinstance(x, (tuple, list)):
                return [listify_tuples(y) for y in x]
            elif isinstance(x, dict):
                return {k: listify_tuples(v) for k, v in x.items()}
            else:
                return x

        if native_values:
            msgs = []

            def legacy_val_info(k):
                if k in legacy_values:
                    val = legacy_values[k]
                    descr = (
                        f"{val} of type {type(val)}, from source {legacy_values.get_rank(k).name}"
                    )
                else:
                    descr = "not provided"
                return f"Legacy value: {descr}"

            def native_val_info(k):
                if k in native_values:
                    val = native_values[k]
                    descr = (
                        f"{val} of type {type(val)}, from source {native_values.get_rank(k).name}"
                    )
                else:
                    descr = "not provided"
                return f"Native value: {descr}"

            for key in sorted(legacy_values.get_keys() | native_values.get_keys()):
                if listify_tuples(legacy_values.get(key)) != native_values.get(key):
                    msgs.append(
                        f"Value mismatch for the option `{key}` in scope [{scope}]:\n"
                        f"{legacy_val_info(key)}\n"
                        f"{native_val_info(key)}"
                    )

            if msgs:

                def log(log_func):
                    for msg in msgs:
                        log_func(msg)
                    log_func(
                        "If you can't resolve this discrepancy, please reach out to the Pants "
                        "development team: https://www.pantsbuild.org/community/getting-help. "
                    )
                    log_func(
                        "The native parser will become the default in 2.23.x, and the legacy parser "
                        "will be removed in 2.24.x. So it is imperative that we find out about any "
                        "discrepancies during this transition period."
                    )
                    log_func(
                        "You can use the global native_options_validation option to configure this check."
                    )

                if self._native_options_validation == NativeOptionsValidation.warning:
                    log(logger.warning)
                elif self._native_options_validation == NativeOptionsValidation.error:
                    log(logger.error)
                    raise Exception("Option value mismatches detected, aborting.")
        # TODO: In a future release, switch to the native_values as authoritative.
        return legacy_values

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
        parser = self.get_parser(scope)
        # Sort the arguments, so that the fingerprint is consistent.
        for _, kwargs in sorted(parser.option_registrations_iter()):
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
