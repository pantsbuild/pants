# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
from dataclasses import dataclass
from fnmatch import fnmatch, fnmatchcase
from typing import Any, Iterable, Iterator, Sequence

from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRulesError
from pants.engine.internals.target_adaptor import TargetAdaptor


class BuildFileVisibilityRulesError(DependencyRulesError):
    pass


@dataclass(frozen=True)
class VisibilityRule:
    """A single rule with an associated action when matched against a given path."""

    action: DependencyRuleAction
    path_pattern: str

    @classmethod
    def parse(cls, rule: str) -> VisibilityRule:
        if not isinstance(rule, str):
            raise ValueError(f"expected a path pattern string but got: {rule!r}")
        if rule.startswith("!"):
            action = DependencyRuleAction.DENY
            pattern = rule[1:]
        elif rule.startswith("?"):
            action = DependencyRuleAction.WARN
            pattern = rule[1:]
        else:
            action = DependencyRuleAction.ALLOW
            pattern = rule
        return cls(action, pattern)

    def match(self, path: str, relpath: str) -> bool:
        pattern = relpath if self.path_pattern == "." else self.path_pattern
        if pattern.startswith("./"):
            pattern = relpath + pattern[1:]
        return fnmatch(path, pattern)


def flatten(xs) -> Iterator[str]:
    """Return an iterator with values, regardless of the nesting of the input."""
    if isinstance(xs, str):
        yield xs
    elif isinstance(xs, Iterable):
        yield from itertools.chain.from_iterable(flatten(x) for x in xs)
    elif type(xs).__name__ == "Registrar":
        yield str(xs)
    else:
        raise ValueError(f"expected a string but got: {xs!r}")


@dataclass(frozen=True)
class VisibilityRuleSet:
    """An ordered set of rules that applies to some set of target types."""

    target_type_patterns: Sequence[str]
    rules: Sequence[VisibilityRule]

    @classmethod
    def parse(cls, arg: Any) -> VisibilityRuleSet:
        """Translate input `arg` from BUILD file call.

        The arg is a rule spec tuple with two or more elements, where the first is the target type
        pattern(s) and the rest are rules.
        """
        if not isinstance(arg, Sequence) or isinstance(arg, str) or len(arg) < 2:
            raise ValueError(
                "Invalid rule spec, expected (<target type pattern(s)>, <rule>, ...) "
                f"but got: {arg!r}"
            )

        try:
            targets, rules = flatten(arg[0]), flatten(arg[1:])
            return cls(tuple(targets), tuple(map(VisibilityRule.parse, rules)))
        except ValueError as e:
            raise ValueError(f"Invalid rule spec, {e}") from e

    def match(self, target: TargetAdaptor) -> bool:
        return any(fnmatchcase(target.type_alias, pattern) for pattern in self.target_type_patterns)
