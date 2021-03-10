# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import copy
import logging
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import warn_or_error
from pants.option.arg_splitter import ArgSplitter, HelpRequest
from pants.option.config import Config
from pants.option.option_util import is_list_option
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.parser import Parser
from pants.option.parser_hierarchy import ParserHierarchy, all_enclosing_scopes, enclosing_scope
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION, ScopeInfo
from pants.util.memo import memoized_method
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


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

    class FrozenOptionsError(Exception):
        """Options are frozen and can't be mutated."""

    class DuplicateScopeError(Exception):
        """More than one registration occurred for the same scope."""

    class AmbiguousPassthroughError(Exception):
        """More than one goal was passed along with passthrough args."""

    @classmethod
    def complete_scopes(cls, scope_infos: Iterable[ScopeInfo]) -> FrozenOrderedSet[ScopeInfo]:
        """Expand a set of scopes to include all enclosing scopes.

        E.g., if the set contains `foo.bar.baz`, ensure that it also contains `foo.bar` and `foo`.

        Also adds any deprecated scopes.
        """
        ret: OrderedSet[ScopeInfo] = OrderedSet()
        original_scopes: Dict[str, ScopeInfo] = {}
        for si in sorted(scope_infos, key=lambda si: si.scope):
            ret.add(si)
            if si.scope in original_scopes:
                raise cls.DuplicateScopeError(
                    "Scope `{}` claimed by {}, was also claimed by {}.".format(
                        si.scope, si, original_scopes[si.scope]
                    )
                )
            original_scopes[si.scope] = si
            if si.deprecated_scope:
                ret.add(ScopeInfo(si.deprecated_scope, si.optionable_cls))
                original_scopes[si.deprecated_scope] = si

        # TODO: Once scope name validation is enforced (so there can be no dots in scope name
        # components) we can replace this line with `for si in scope_infos:`, because it will
        # not be possible for a deprecated_scope to introduce any new intermediate scopes.
        for si in copy.copy(ret):
            for scope in all_enclosing_scopes(si.scope, allow_global=False):
                if scope not in original_scopes:
                    ret.add(ScopeInfo(scope))
        return FrozenOrderedSet(ret)

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        config: Config,
        known_scope_infos: Iterable[ScopeInfo],
        args: Sequence[str],
        bootstrap_option_values: Optional[OptionValueContainer] = None,
        allow_unknown_options: bool = False,
    ) -> Options:
        """Create an Options instance.

        :param env: a dict of environment variables.
        :param config: data from a config file.
        :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
        :param args: a list of cmd-line args; defaults to `sys.argv` if None is supplied.
        :param bootstrap_option_values: An optional namespace containing the values of bootstrap
               options. We can use these values when registering other options.
        """
        # We need parsers for all the intermediate scopes, so inherited option values
        # can propagate through them.
        complete_known_scope_infos = cls.complete_scopes(known_scope_infos)
        splitter = ArgSplitter(complete_known_scope_infos, get_buildroot())
        split_args = splitter.split_args(args)

        if split_args.passthru and len(split_args.goals) > 1:
            raise cls.AmbiguousPassthroughError(
                f"Specifying multiple goals (in this case: {split_args.goals}) "
                "along with passthrough args (args after `--`) is ambiguous.\n"
                "Try either specifying only a single goal, or passing the passthrough args "
                "directly to the relevant consumer via its associated flags."
            )

        if bootstrap_option_values:
            spec_files = bootstrap_option_values.spec_files
            if spec_files:
                for spec_file in spec_files:
                    with open(spec_file, "r") as f:
                        split_args.specs.extend(
                            [line for line in [line.strip() for line in f] if line]
                        )

        help_request = splitter.help_request

        parser_hierarchy = ParserHierarchy(env, config, complete_known_scope_infos)
        known_scope_to_info = {s.scope: s for s in complete_known_scope_infos}
        return cls(
            goals=split_args.goals,
            scope_to_flags=split_args.scope_to_flags,
            specs=split_args.specs,
            passthru=split_args.passthru,
            help_request=help_request,
            parser_hierarchy=parser_hierarchy,
            bootstrap_option_values=bootstrap_option_values,
            known_scope_to_info=known_scope_to_info,
            allow_unknown_options=allow_unknown_options,
        )

    def __init__(
        self,
        goals: List[str],
        scope_to_flags: Dict[str, List[str]],
        specs: List[str],
        passthru: List[str],
        help_request: Optional[HelpRequest],
        parser_hierarchy: ParserHierarchy,
        bootstrap_option_values: Optional[OptionValueContainer],
        known_scope_to_info: Dict[str, ScopeInfo],
        allow_unknown_options: bool = False,
    ) -> None:
        """The low-level constructor for an Options instance.

        Dependees should use `Options.create` instead.
        """
        self._goals = goals
        self._scope_to_flags = scope_to_flags
        self._specs = specs
        self._passthru = passthru
        self._help_request = help_request
        self._parser_hierarchy = parser_hierarchy
        self._bootstrap_option_values = bootstrap_option_values
        self._known_scope_to_info = known_scope_to_info
        self._allow_unknown_options = allow_unknown_options
        self._frozen = False

    # TODO: Eliminate this in favor of a builder/factory.
    @property
    def frozen(self) -> bool:
        """Whether or not this Options object is frozen from writes."""
        return self._frozen

    @property
    def help_request(self) -> Optional[HelpRequest]:
        """
        :API: public
        """
        return self._help_request

    @property
    def specs(self) -> List[str]:
        """The specifications to operate on, e.g. the target addresses and the file names.

        :API: public
        """
        return self._specs

    @property
    def goals(self) -> List[str]:
        """The requested goals, in the order specified on the cmd line.

        :API: public
        """
        return self._goals

    @property
    def known_scope_to_info(self) -> Dict[str, ScopeInfo]:
        return self._known_scope_to_info

    @property
    def scope_to_flags(self) -> Dict[str, List[str]]:
        return self._scope_to_flags

    def freeze(self) -> None:
        """Freezes this Options instance."""
        self._frozen = True

    def verify_configs(self, global_config: Config) -> None:
        """Verify all loaded configs have correct scopes and options."""

        error_log = []
        for config in global_config.configs():
            for section in config.sections():
                scope = GLOBAL_SCOPE if section == GLOBAL_SCOPE_CONFIG_SECTION else section
                try:
                    # TODO(#10834): this is broken for subscopes. Once we fix global options to no
                    #  longer be included in self.for_scope(), we should set
                    #  inherit_from_enclosing_scope=True.
                    valid_options_under_scope = set(
                        self.for_scope(scope, inherit_from_enclosing_scope=False)
                    )
                # Only catch ConfigValidationError. Other exceptions will be raised directly.
                except Config.ConfigValidationError:
                    error_log.append(f"Invalid scope [{section}] in {config.config_path}")
                else:
                    # All the options specified under [`section`] in `config` excluding bootstrap defaults.
                    all_options_under_scope = set(config.values.options(section)) - set(
                        config.values.defaults
                    )
                    for option in sorted(all_options_under_scope):
                        if option not in valid_options_under_scope:
                            error_log.append(
                                f"Invalid option '{option}' under [{section}] in {config.config_path}"
                            )

        if error_log:
            for error in error_log:
                logger.error(error)
            raise Config.ConfigValidationError(
                "Invalid config entries detected. See log for details on which entries to update or "
                "remove.\n(Specify --no-verify-config to disable this check.)"
            )

    def drop_flag_values(self) -> Options:
        """Returns a copy of these options that ignores values specified via flags.

        Any pre-cached option values are cleared and only option values that come from option
        defaults, the config or the environment are used.
        """
        # An empty scope_to_flags to force all values to come via the config -> env hierarchy alone
        # and empty values in case we already cached some from flags.
        no_flags: Dict[str, List[str]] = {}
        return Options(
            goals=self._goals,
            scope_to_flags=no_flags,
            specs=self._specs,
            passthru=self._passthru,
            help_request=self._help_request,
            parser_hierarchy=self._parser_hierarchy,
            bootstrap_option_values=self._bootstrap_option_values,
            known_scope_to_info=self._known_scope_to_info,
        )

    def is_known_scope(self, scope: str) -> bool:
        """Whether the given scope is known by this instance.

        :API: public
        """
        return scope in self._known_scope_to_info

    def _assert_not_frozen(self) -> None:
        if self._frozen:
            raise self.FrozenOptionsError(f"cannot mutate frozen Options instance {self!r}.")

    def register(self, scope: str, *args, **kwargs) -> None:
        """Register an option in the given scope."""
        self._assert_not_frozen()
        self.get_parser(scope).register(*args, **kwargs)
        deprecated_scope = self.known_scope_to_info[scope].deprecated_scope
        if deprecated_scope:
            self.get_parser(deprecated_scope).register(*args, **kwargs)

    def registration_function_for_optionable(self, optionable_class):
        """Returns a function for registering options on the given scope."""
        self._assert_not_frozen()

        # TODO(benjy): Make this an instance of a class that implements __call__, so we can
        # docstring it, and so it's less weird than attaching properties to a function.
        def register(*args, **kwargs):
            self.register(optionable_class.options_scope, *args, **kwargs)

        # Clients can access the bootstrap option values as register.bootstrap.
        register.bootstrap = self.bootstrap_option_values()
        # Clients can access the scope as register.scope.
        register.scope = optionable_class.options_scope
        return register

    def get_parser(self, scope: str) -> Parser:
        """Returns the parser for the given scope, so code can register on it directly."""
        self._assert_not_frozen()
        return self._parser_hierarchy.get_parser_by_scope(scope)

    def walk_parsers(self, callback):
        self._assert_not_frozen()
        self._parser_hierarchy.walk(callback)

    def _check_and_apply_deprecations(self, scope, values):
        """Checks whether a ScopeInfo has options specified in a deprecated scope.

        There are two related cases here. Either:
          1) The ScopeInfo has an associated deprecated_scope that was replaced with a non-deprecated
             scope, meaning that the options temporarily live in two locations.
          2) The entire ScopeInfo is deprecated (as in the case of deprecated SubsystemDependencies),
             meaning that the options live in one location.

        In the first case, this method has the sideeffect of merging options values from deprecated
        scopes into the given values.
        """
        si = self.known_scope_to_info[scope]

        # If this Scope is itself deprecated, report that.
        if si.removal_version:
            explicit_keys = self.for_scope(
                scope, inherit_from_enclosing_scope=False
            ).get_explicit_keys()
            if explicit_keys:
                warn_or_error(
                    removal_version=si.removal_version,
                    deprecated_entity_description=f"scope {scope}",
                    hint=si.removal_hint,
                )

        # Check if we're the new name of a deprecated scope, and clone values from that scope.
        # Note that deprecated_scope and scope share the same Optionable class, so deprecated_scope's
        # Optionable has a deprecated_options_scope equal to deprecated_scope. Therefore we must
        # check that scope != deprecated_scope to prevent infinite recursion.
        deprecated_scope = si.deprecated_scope
        if deprecated_scope is not None and scope != deprecated_scope:
            # Do the deprecation check only on keys that were explicitly set on the deprecated scope
            # (and not on its enclosing scopes).
            explicit_keys = self.for_scope(
                deprecated_scope, inherit_from_enclosing_scope=False
            ).get_explicit_keys()
            if explicit_keys:
                # Update our values with those of the deprecated scope (now including values inherited
                # from its enclosing scope).
                # Note that a deprecated val will take precedence over a val of equal rank.
                # This makes the code a bit neater.
                values.update(self.for_scope(deprecated_scope))

                warn_or_error(
                    removal_version=self.known_scope_to_info[
                        scope
                    ].deprecated_scope_removal_version,
                    deprecated_entity_description=f"scope {deprecated_scope}",
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
        self,
        scope: str,
        inherit_from_enclosing_scope: bool = True,
    ) -> OptionValueContainer:
        """Return the option values for the given scope.

        Values are attributes of the returned object, e.g., options.foo.
        Computed lazily per scope.

        :API: public
        """

        # First get enclosing scope's option values, if any.
        if scope == GLOBAL_SCOPE or not inherit_from_enclosing_scope:
            values_builder = OptionValueContainerBuilder()
        else:
            values_builder = self.for_scope(enclosing_scope(scope)).to_builder()

        # Now add our values.
        flags_in_scope = self._scope_to_flags.get(scope, [])
        parse_args_request = self._make_parse_args_request(flags_in_scope, values_builder)
        values = self._parser_hierarchy.get_parser_by_scope(scope).parse_args(parse_args_request)

        # Check for any deprecation conditions, which are evaluated using `self._flag_matchers`.
        if inherit_from_enclosing_scope:
            values_builder = values.to_builder()
            self._check_and_apply_deprecations(scope, values_builder)
            values = values_builder.build()

        return values

    def get_fingerprintable_for_scope(
        self,
        bottom_scope: str,
        fingerprint_key: str = "fingerprint",
        invert: bool = False,
    ):
        """Returns a list of fingerprintable (option type, option value) pairs for the given scope.

        Fingerprintable options are options registered via a "fingerprint=True" kwarg. This flag
        can be parameterized with `fingerprint_key` for special cases.

        This method also searches enclosing options scopes of `bottom_scope` to determine the set of
        fingerprintable pairs.

        :param bottom_scope: The scope to gather fingerprintable options for.
        :param fingerprint_key: The option kwarg to match against (defaults to 'fingerprint').
        :param invert: Whether or not to invert the boolean check for the fingerprint_key value.

        :API: public
        """

        fingerprint_default = bool(invert)
        pairs = []

        # Note that we iterate over options registered at `bottom_scope` and at all
        # enclosing scopes, since option-using code can read those values indirectly
        # via its own OptionValueContainer, so they can affect that code's output.
        for registration_scope in all_enclosing_scopes(bottom_scope):
            parser = self._parser_hierarchy.get_parser_by_scope(registration_scope)
            # Sort the arguments, so that the fingerprint is consistent.
            for (_, kwargs) in sorted(parser.option_registrations_iter()):
                if kwargs.get("recursive", False) and not kwargs.get("recursive_root", False):
                    continue  # We only need to fprint recursive options once.
                if not kwargs.get(fingerprint_key, fingerprint_default):
                    continue
                # Note that we read the value from scope, even if the registration was on an enclosing
                # scope, to get the right value for recursive options (and because this mirrors what
                # option-using code does).
                val = self.for_scope(bottom_scope)[kwargs["dest"]]
                # If we have a list then we delegate to the fingerprinting implementation of the members.
                if is_list_option(kwargs):
                    val_type = kwargs.get("member_type", str)
                else:
                    val_type = kwargs.get("type", str)
                pairs.append((val_type, val))
        return pairs

    def __getitem__(self, scope: str) -> OptionValueContainer:
        # TODO(John Sirois): Mainly supports use of dict<str, dict<str, str>> for mock options in tests,
        # Consider killing if tests consolidate on using TestOptions instead of the raw dicts.
        return self.for_scope(scope)

    def bootstrap_option_values(self) -> Optional[OptionValueContainer]:
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
