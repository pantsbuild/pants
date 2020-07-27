# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict

from pants.option.parser_hierarchy import enclosing_scope
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE


class _FakeOptionValues:
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
                # TODO: This is _very_ partial support for passthrough args: this should be
                # inspecting the kwargs of option registrations to decide which arguments to
                # extend: this explicit `passthrough_args` argument is only passthrough because
                # it is marked as such.
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

        def items(self):
            return list(options.items())

        @property
        def scope_to_flags(self):
            return {}

        def get_fingerprintable_for_scope(self, bottom_scope):
            """Returns a list of fingerprintable (option type, option value) pairs for the given
            scope.

            Note that this method only collects values for a single scope, NOT from
            all enclosing scopes as in the Options class!

            :param str bottom_scope: The scope to gather fingerprintable options for.
            """
            pairs = []
            option_values = self.for_scope(bottom_scope)
            for option_name, option_type in fingerprintable[bottom_scope].items():
                pairs.append((option_type, option_values[option_name]))
            return pairs

        def __getitem__(self, scope):
            return self.for_scope(scope)

    return FakeOptions()
