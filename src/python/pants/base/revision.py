# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from functools import total_ordering
from itertools import zip_longest


@total_ordering
class Revision:
    """Represents a software revision that is comparable to another revision describing the same
    software.

    :API: public
    """

    class BadRevision(Exception):
        """Indicates a problem parsing a revision."""

    @classmethod
    def _parse_atom(cls, atom):
        try:
            return int(atom)
        except ValueError:
            return atom

    @classmethod
    def semver(cls, rev) -> "Revision":
        """Attempts to parse a Revision from a semantic version.

        See http://semver.org/ for the full specification.

        :API: public
        """

        def parse_extra(delimiter, value):
            if not value:
                return None, None
            else:
                components = value.split(delimiter, 1)
                return components[0], None if len(components) == 1 else components[1]

        def parse_patch(patch):
            patch, pre_release = parse_extra("-", patch)
            if pre_release:
                pre_release, build = parse_extra("+", pre_release)
            else:
                patch, build = parse_extra("+", patch)
            return patch, pre_release, build

        def parse_components(value):
            if not value:
                yield None
            else:
                for atom in value.split("."):
                    yield cls._parse_atom(atom)

        try:
            major, minor, patch = rev.split(".", 2)
            patch, pre_release, build = parse_patch(patch)
            components = [int(major), int(minor), int(patch)]
            components.extend(parse_components(pre_release))
            components.extend(parse_components(build))
            return cls(*components)
        except ValueError:
            raise cls.BadRevision("Failed to parse '{}' as a semantic version number".format(rev))

    @classmethod
    def lenient(cls, rev) -> "Revision":
        """A lenient revision parser that tries to split the version into logical components with
        heuristics inspired by PHP's version_compare.

        :API: public
        """
        rev = re.sub(r"(\d)([a-zA-Z])", r"\1.\2", rev)
        rev = re.sub(r"([a-zA-Z])(\d)", r"\1.\2", rev)
        return cls(*list(map(cls._parse_atom, re.split(r"[.+_\-]", rev))))

    def __init__(self, *components):
        self._components = components

    @property
    def components(self):
        """Returns a list of this revision's components from most major to most minor.

        :API: public
        """
        return list(self._components)

    def _is_valid_operand(self, other):
        return hasattr(other, "_components")

    def _fill_value_if_missing(self, ours, theirs):
        if theirs is None:
            return ours, type(ours)()  # gets type's zero-value, e.g. 0 or ""
        elif ours is None:
            return type(theirs)(), theirs
        return ours, theirs

    def _stringify_if_different_types(self, ours, theirs):
        if any(isinstance(v, str) for v in (ours, theirs)):
            return str(ours), str(theirs)
        return ours, theirs

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, ", ".join(map(repr, self._components)))

    def __eq__(self, other):
        if not self._is_valid_operand(other):
            return False  # TODO(#6071): typically this should return NotImplemented.
            # Returning False for now to avoid changing prior API.
        return tuple(self._components) == tuple(other._components)

    def __lt__(self, other):
        if not self._is_valid_operand(other):
            return AttributeError  # TODO(#6071): typically this should return NotImplemented.
            # Returning AttributeError for now to avoid changing prior API.
        for ours, theirs in zip_longest(self._components, other._components, fillvalue=None):
            if ours != theirs:
                ours, theirs = self._fill_value_if_missing(ours, theirs)
                ours, theirs = self._stringify_if_different_types(ours, theirs)
                if ours == theirs:
                    continue
                return ours < theirs
        return False

    def __hash__(self):
        return hash(self._components)

    def __str__(self):
        return ".".join(str(c) for c in self._components)
