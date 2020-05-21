# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict

from pants.option.global_options import GlobalOptions
from pants.option.option_util import is_list_option
from pants.option.parser import Parser
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE


class _FakeOptionValues(object):
    def __init__(self, option_values):
        self._option_values = option_values

    def __iter__(self):
        return iter(self._option_values.keys())

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        if hasattr(self, key):
            return getattr(self, key, default)
        return default

    def __getattr__(self, key):
        try:
            value = self._option_values[key]
        except KeyError:
            # Instead of letting KeyError raise here, re-raise an AttributeError to not break getattr().
            raise AttributeError(key)
        return value.value if isinstance(value, RankedValue) else value

    def get_rank(self, key):
        value = self._option_values[key]
        return value.rank if isinstance(value, RankedValue) else Rank.FLAG

    def is_flagged(self, key):
        return self.get_rank(key) == Rank.FLAG

    def is_default(self, key):
        return self.get_rank(key) in (Rank.NONE, Rank.HARDCODED)

    @property
    def option_values(self):
        return self._option_values


def _options_registration_function(defaults, fingerprintables):
    def register(*args, **kwargs):
        _, option_dest = Parser.parse_name_and_dest(*args, **kwargs)

        default = kwargs.get("default")
        if default is None:
            if kwargs.get("type") == bool:
                default = False
            if kwargs.get("type") == list:
                default = []
        defaults[option_dest] = RankedValue(Rank.HARDCODED, default)

        fingerprint = kwargs.get("fingerprint", False)
        if fingerprint:
            if is_list_option(kwargs):
                val_type = kwargs.get("member_type", str)
            else:
                val_type = kwargs.get("type", str)
            fingerprintables[option_dest] = val_type

    return register


def create_options(options, passthru_args=None, fingerprintable_options=None):
    """Create a fake Options object for testing.

    Note that the returned object only provides access to the provided options values. There is
    no registration mechanism on this object. Code under test shouldn't care about resolving
    cmd-line flags vs. config vs. env vars etc. etc.

    :param dict options: A dict of scope -> (dict of option name -> value).
    :param list passthru_args: A list of passthrough command line argument values.
    :param dict fingerprintable_options: A dict of scope -> (dict of option name -> option type).
                                         This registry should contain entries for any of the
                                         `options` that are expected to contribute to fingerprinting.
    :returns: An fake `Options` object encapsulating the given scoped options.
    """
    fingerprintable = fingerprintable_options or defaultdict(dict)

    class FakeOptions:
        def for_scope(self, scope):
            # TODO(John Sirois): Some users pass in A dict of scope -> _FakeOptionValues instead of a
            # dict of scope -> (dict of option name -> value).  Clean up these usages and kill this
            # accommodation.
            options_for_this_scope = options.get(scope) or {}
            if isinstance(options_for_this_scope, _FakeOptionValues):
                options_for_this_scope = options_for_this_scope.option_values

            if passthru_args:
                pa = options_for_this_scope.get("passthrough_args", [])
                if isinstance(pa, RankedValue):
                    pa = pa.value
                options_for_this_scope["passthrough_args"] = [*pa, *passthru_args]

            scoped_options = {}
            if scope:
                scoped_options.update(self.for_scope(enclosing_scope(scope)).option_values)
            scoped_options.update(options_for_this_scope)
            return _FakeOptionValues(scoped_options)

        def for_global_scope(self):
            return self.for_scope(GLOBAL_SCOPE)

        def passthru_args_for_scope(self, scope):
            return passthru_args or []

        def items(self):
            return list(options.items())

        @property
        def scope_to_flags(self):
            return {}

        def get_fingerprintable_for_scope(self, bottom_scope, include_passthru=False):
            """Returns a list of fingerprintable (option type, option value) pairs for the given
            scope.

            Note that this method only collects values for a single scope, NOT from
            all enclosing scopes as in the Options class!

            :param str bottom_scope: The scope to gather fingerprintable options for.
            :param bool include_passthru: Whether to include passthru args captured by `bottom_scope` in the
                                          fingerprintable options.
            """
            pairs = []
            if include_passthru:
                pu_args = self.passthru_args_for_scope(bottom_scope)
                pairs.extend((str, arg) for arg in pu_args)

            option_values = self.for_scope(bottom_scope)
            for option_name, option_type in fingerprintable[bottom_scope].items():
                pairs.append((option_type, option_values[option_name]))
            return pairs

        def __getitem__(self, scope):
            return self.for_scope(scope)

    return FakeOptions()


def create_options_for_optionables(
    optionables, options=None, options_fingerprintable=None, passthru_args=None
):
    """Create a fake Options object for testing with appropriate defaults for the given optionables.

    Any scoped `options` provided will override defaults, behaving as-if set on the command line.

    :param iterable optionables: A series of `Optionable` types to register default options for.
    :param dict options: A dict of scope -> (dict of option name -> value) representing option values
                         explicitly set via the command line.
    :param dict options_fingerprintable: A dict of scope -> (dict of option name -> option type)
                                         representing the fingerprintable options
                                         and the scopes they are registered for.
    :param list passthru_args: A list of passthrough args (specified after `--` on the command line).
    :returns: A fake `Options` object with defaults populated for the given `optionables` and any
              explicitly set `options` overlayed.
    """
    all_options = defaultdict(dict)
    fingerprintable_options = defaultdict(dict)
    bootstrap_option_values = None

    if options_fingerprintable:
        for scope, opts in options_fingerprintable.items():
            fingerprintable_options[scope].update(opts)

    def register_func(on_scope):
        scoped_options = all_options[on_scope]
        scoped_fingerprintables = fingerprintable_options[on_scope]
        register = _options_registration_function(scoped_options, scoped_fingerprintables)
        register.bootstrap = bootstrap_option_values
        register.scope = on_scope
        return register

    # TODO: This sequence is a bit repetitive of the real registration sequence.

    # Register bootstrap options and grab their default values for use in subsequent registration.
    GlobalOptions.register_bootstrap_options(register_func(GLOBAL_SCOPE))
    bootstrap_option_values = _FakeOptionValues(all_options[GLOBAL_SCOPE].copy())

    # Now register the full global scope options.
    GlobalOptions.register_options(register_func(GLOBAL_SCOPE))

    for optionable in optionables:
        optionable.register_options(register_func(optionable.options_scope))

    if options:
        for scope, opts in options.items():
            all_options[scope].update(opts)

    return create_options(
        all_options, passthru_args=passthru_args, fingerprintable_options=fingerprintable_options
    )
