# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class Scope(frozenset):
    """Represents a set of dependency scope names.

    It is the responsibility of individual tasks to read and respect these scopes by using functions
    such as target.closure() and BuildGraph.closure().
    """

    @classmethod
    def _parse(cls, scope):
        """Parses the input scope into a normalized set of strings.

        :param scope: A string or tuple containing zero or more scope names.
        :return: A set of scope name strings, or a tuple with the default scope name.
        :rtype: set
        """
        if not scope:
            return ("default",)
        if isinstance(scope, str):
            scope = scope.split(" ")
        scope = {str(s).lower() for s in scope if s}
        return scope or ("default",)

    def __new__(cls, scope):
        return super().__new__(cls, cls._parse(scope))

    def in_scope(self, exclude_scopes=None, include_scopes=None):
        """Whether this scope should be included by the given inclusion and exclusion rules.

        :param Scope exclude_scopes: An optional Scope containing scope names to exclude. None (the
          default value) indicates that no filtering should be done based on exclude_scopes.
        :param Scope include_scopes: An optional Scope containing scope names to include. None (the
          default value) indicates that no filtering should be done based on include_scopes.
        :return: True if none of the input scopes are in `exclude_scopes`, and either (a) no include
          scopes are provided, or (b) at least one input scope is included in the `include_scopes` list.
        :rtype: bool
        """
        if include_scopes is not None and not isinstance(include_scopes, Scope):
            raise ValueError(
                "include_scopes must be a Scope instance but was {}.".format(type(include_scopes))
            )
        if exclude_scopes is not None and not isinstance(exclude_scopes, Scope):
            raise ValueError(
                "exclude_scopes must be a Scope instance but was {}.".format(type(exclude_scopes))
            )
        if exclude_scopes and any(s in exclude_scopes for s in self):
            return False
        if include_scopes and not any(s in include_scopes for s in self):
            return False
        return True

    def __add__(self, other):
        return Scope(super().__or__(other))

    def __or__(self, other):
        return Scope(super().__or__(other))

    def __str__(self):
        return " ".join(sorted(self))
