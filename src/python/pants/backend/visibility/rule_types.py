# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
import os.path
from dataclasses import dataclass, field
from fnmatch import fnmatch, fnmatchcase
from pathlib import PurePath
from typing import Any, Iterable, Iterator, Sequence, cast

from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRuleAction,
    DependencyRulesError,
)
from pants.engine.internals.target_adaptor import TargetAdaptor

logger = logging.getLogger(__name__)


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

    def __str__(self) -> str:
        prefix = ""
        if self.action is DependencyRuleAction.DENY:
            prefix = "!"
        elif self.action is DependencyRuleAction.WARN:
            prefix = "?"
        return repr(f"{prefix}{self.path_pattern}")


def flatten(xs) -> Iterator[str]:
    """Return an iterator with values, regardless of the nesting of the input."""
    if isinstance(xs, str):
        yield xs
    elif isinstance(xs, Iterable):
        yield from itertools.chain.from_iterable(flatten(x) for x in xs)
    elif type(xs).__name__ == "Registrar" or isinstance(xs, PurePath):
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


@dataclass(frozen=True)
class BuildFileVisibilityRules(BuildFileDependencyRules):
    path: str
    rulesets: Sequence[VisibilityRuleSet]

    @staticmethod
    def create_parser_state(
        path: str, parent: BuildFileDependencyRules | None
    ) -> BuildFileDependencyRulesParserState:
        return BuildFileVisibilityRulesParserState(path, cast(BuildFileVisibilityRules, parent))

    @staticmethod
    def check_dependency_rules(
        *,
        source_adaptor: TargetAdaptor,
        source_path: str,
        dependencies_rules: BuildFileDependencyRules | None,
        target_adaptor: TargetAdaptor,
        target_path: str,
        dependents_rules: BuildFileDependencyRules | None,
    ) -> DependencyRuleAction:
        """The source of the dependency has the dependencies field, the target of the dependency is
        the one listed as a value in the dependencies field.

        The `__dependencies_rules__` are the rules applicable for the source path.
        The `__dependents_rules__` are the rules applicable for the target path.

        Return dependency rule action ALLOW, DENY or WARN. WARN is effectively the same as ALLOW,
        but with a logged warning.
        """
        # We can safely cast the `dependencies_rules` and `dependents_rules` here as they're the
        # same type as the class being used to call `check_dependency_rules()`.

        # Check outgoing dependency action
        outgoing = (
            cast(BuildFileVisibilityRules, dependencies_rules).get_action(
                source_adaptor,
                target_path,
                relpath=source_path,
                outgoing_dependency=True,
            )
            if dependencies_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if outgoing is None:
            dep_rules = cast(BuildFileVisibilityRules, dependencies_rules)
            raise BuildFileVisibilityRulesError(
                f"There is no matching dependencies rule for the `{source_adaptor.type_alias}` "
                f"target {source_path}:{source_adaptor.name or os.path.basename(source_path)} "
                f"for the dependency on the `{target_adaptor.type_alias}` target {target_path}:"
                f"{target_adaptor.name or os.path.basename(target_path)} in {dep_rules.path}"
            )
        if outgoing == DependencyRuleAction.DENY:
            return outgoing

        # Check incoming dependency action
        incoming = (
            cast(BuildFileVisibilityRules, dependents_rules).get_action(
                target_adaptor,
                source_path,
                relpath=target_path,
                outgoing_dependency=False,
            )
            if dependents_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if incoming is None:
            dep_rules = cast(BuildFileVisibilityRules, dependents_rules)
            raise BuildFileVisibilityRulesError(
                f"There is no matching dependents rule for the `{target_adaptor.type_alias}` "
                f"target {target_path}:{target_adaptor.name or os.path.basename(target_path)} "
                f"for the dependency from the `{source_adaptor.type_alias}` target {source_path}:"
                f"{source_adaptor.name or os.path.basename(source_path)} in {dep_rules.path}"
            )
        return incoming if incoming != DependencyRuleAction.ALLOW else outgoing

    def get_action(
        self,
        target: TargetAdaptor,
        path: str,
        relpath: str,
        outgoing_dependency: bool,
    ) -> DependencyRuleAction | None:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        ruleset = self.get_ruleset(target)
        if ruleset is None:
            return None
        for visibility_rule in ruleset.rules:
            if visibility_rule.match(path, relpath):
                if visibility_rule.action != DependencyRuleAction.ALLOW:
                    target_addr = f"{relpath}:{target.name or os.path.basename(relpath)}"
                    target_type = target.type_alias
                    if outgoing_dependency:
                        logger.debug(
                            f"{visibility_rule.action.name}: the `{target_type}` target "
                            f"{target_addr} dependency to a target at {path} by dependency rule "
                            f"{visibility_rule} declared in {self.path}"
                        )
                    else:
                        logger.debug(
                            f"{visibility_rule.action.name}: dependency on the `{target_type}` "
                            f"target {target_addr} from a target at {path} by dependent rule "
                            f"{visibility_rule} declared in {self.path}"
                        )
                return visibility_rule.action
        return None

    def get_ruleset(self, target: TargetAdaptor) -> VisibilityRuleSet | None:
        for ruleset in self.rulesets:
            if ruleset.match(target):
                return ruleset
        return None


@dataclass
class BuildFileVisibilityRulesParserState(BuildFileDependencyRulesParserState):
    path: str
    parent: BuildFileVisibilityRules | None
    rulesets: list[VisibilityRuleSet] = field(default_factory=list)

    def get_frozen_dependency_rules(self) -> BuildFileDependencyRules | None:
        if not self.rulesets:
            return self.parent
        else:
            return BuildFileVisibilityRules(self.path, tuple(self.rulesets))

    def set_dependency_rules(
        self,
        build_file: str,
        *args,
        extend: bool = False,
        **kwargs,
    ) -> None:
        try:
            self.rulesets = [VisibilityRuleSet.parse(arg) for arg in args if arg]
            self.path = build_file
        except ValueError as e:
            raise BuildFileVisibilityRulesError(f"{build_file}: {e}") from e

        if extend and self.parent:
            self.rulesets.extend(self.parent.rulesets)
