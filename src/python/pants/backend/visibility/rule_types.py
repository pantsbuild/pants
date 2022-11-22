# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
import os.path
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePath
from pprint import pformat
from typing import Any, Iterable, Iterator, Sequence, cast

from pants.backend.visibility.glob import PathGlob
from pants.engine.addresses import Address
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRuleAction,
    DependencyRuleApplication,
    DependencyRulesError,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class BuildFileVisibilityRulesError(DependencyRulesError):
    @classmethod
    def create(
        cls,
        kind: str,
        rules: BuildFileVisibilityRules,
        ruleset: VisibilityRuleSet | None,
        origin_address: Address,
        origin_adaptor: TargetAdaptor,
        dependency_address: Address,
        dependency_adaptor: TargetAdaptor,
    ) -> BuildFileVisibilityRulesError:
        example = (
            pformat((ruleset.target_type_patterns, *map(str, ruleset.rules), "!*"))
            if ruleset is not None
            else '(<target patterns>, <existing rules...>, "!*"),'
        )
        return cls(
            softwrap(
                f"""
                There is no matching rule from the `{kind}` defined in {rules.path} for the
                `{origin_adaptor.type_alias}` target {origin_address} for the dependency on the
                `{dependency_adaptor.type_alias}` target {dependency_address}

                Consider adding the required catch-all rule at the end of the rules spec.  Example
                adding a "deny all" at the end:

                  {example}
                """
            )
        )


@dataclass(frozen=True)
class VisibilityRule:
    """A single rule with an associated action when matched against a given path."""

    action: DependencyRuleAction
    glob: PathGlob

    @classmethod
    def parse(
        cls,
        rule: str,
        relpath: str,
    ) -> VisibilityRule:
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
        return cls(action, PathGlob.parse(pattern, relpath))

    def match(self, path: str, relpath: str) -> bool:
        return self.glob.match(path, relpath)

    def __str__(self) -> str:
        prefix = ""
        if self.action is DependencyRuleAction.DENY:
            prefix = "!"
        elif self.action is DependencyRuleAction.WARN:
            prefix = "?"
        return f"{prefix}{self.glob.raw}"


def flatten(xs) -> Iterator[str]:
    """Return an iterator with values, regardless of the nesting of the input."""
    if isinstance(xs, str):
        yield from (x.strip() for x in xs.splitlines())
    elif isinstance(xs, Iterable):
        yield from itertools.chain.from_iterable(flatten(x) for x in xs)
    elif type(xs).__name__ == "Registrar" or isinstance(xs, PurePath):
        yield str(xs)
    else:
        raise ValueError(f"expected a string but got: {xs!r}")


@dataclass(frozen=True)
class VisibilityRuleSet:
    """An ordered set of rules that applies to some set of target types."""

    build_file: str
    target_type_patterns: Sequence[str]
    rules: Sequence[VisibilityRule]

    @classmethod
    def parse(cls, build_file: str, arg: Any) -> VisibilityRuleSet:
        """Translate input `arg` from BUILD file call.

        The arg is a rule spec tuple with two or more elements, where the first is the target type
        pattern(s) and the rest are rules.
        """
        if not isinstance(arg, Sequence) or isinstance(arg, str) or len(arg) < 2:
            raise ValueError(
                "Invalid rule spec, expected (<target type pattern(s)>, <rule>, ...) "
                f"but got: {arg!r}"
            )

        relpath = os.path.dirname(build_file)
        try:
            targets, rules = flatten(arg[0]), flatten(arg[1:])
            return cls(
                build_file,
                tuple(targets),
                tuple(
                    VisibilityRule.parse(rule, relpath)
                    for rule in rules
                    if not cls._noop_rule(rule)
                ),
            )
        except ValueError as e:
            raise ValueError(f"Invalid rule spec, {e}") from e

    def __str__(self) -> str:
        return self.build_file

    @staticmethod
    def _noop_rule(rule: str) -> bool:
        return not rule or rule.startswith("#")

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
        origin_address: Address,
        origin_adaptor: TargetAdaptor,
        dependencies_rules: BuildFileDependencyRules | None,
        dependency_address: Address,
        dependency_adaptor: TargetAdaptor,
        dependents_rules: BuildFileDependencyRules | None,
    ) -> DependencyRuleApplication:
        """Check all rules for any that apply to the relation between the two targets.

        The `__dependencies_rules__` are the rules applicable for the origin target.
        The `__dependents_rules__` are the rules applicable for the dependency target.

        Return dependency rule application describing the resulting action to take: ALLOW, DENY or
        WARN. WARN is effectively the same as ALLOW, but with a logged warning.
        """
        # We can safely cast the `dependencies_rules` and `dependents_rules` here as they're the
        # same type as the class being used to call `check_dependency_rules()`.

        # Check outgoing dependency action
        out_ruleset, out_action, out_pattern = (
            cast(BuildFileVisibilityRules, dependencies_rules).get_action(
                target=origin_adaptor,
                address=dependency_address,
                relpath=origin_address.spec_path,
                outgoing_dependency=True,
            )
            if dependencies_rules is not None
            else (None, DependencyRuleAction.ALLOW, None)
        )
        if out_action is None:
            raise BuildFileVisibilityRulesError.create(
                kind="__dependencies_rules__",
                rules=cast(BuildFileVisibilityRules, dependencies_rules),
                ruleset=out_ruleset,
                origin_address=origin_address,
                origin_adaptor=origin_adaptor,
                dependency_address=dependency_address,
                dependency_adaptor=dependency_adaptor,
            )

        # Check incoming dependency action
        in_ruleset, in_action, in_pattern = (
            cast(BuildFileVisibilityRules, dependents_rules).get_action(
                target=dependency_adaptor,
                address=origin_address,
                relpath=dependency_address.spec_path,
                outgoing_dependency=False,
            )
            if dependents_rules is not None
            else (None, DependencyRuleAction.ALLOW, None)
        )
        if in_action is None:
            raise BuildFileVisibilityRulesError.create(
                kind="__dependents_rules__",
                rules=cast(BuildFileVisibilityRules, dependents_rules),
                ruleset=in_ruleset,
                origin_address=origin_address,
                origin_adaptor=origin_adaptor,
                dependency_address=dependency_address,
                dependency_adaptor=dependency_adaptor,
            )
        if in_action is DependencyRuleAction.DENY or out_action is DependencyRuleAction.ALLOW:
            action = in_action
        else:
            action = out_action
        source_rule = f"{out_ruleset}[{out_pattern}]" if out_ruleset else origin_address.spec_path
        target_rule = f"{in_ruleset}[{in_pattern}]" if in_ruleset else dependency_address.spec_path
        return DependencyRuleApplication(
            action=action,
            rule_description=f"{source_rule} -> {target_rule}",
            origin_address=origin_address,
            origin_type=origin_adaptor.type_alias,
            dependency_address=dependency_address,
            dependency_type=dependency_adaptor.type_alias,
        )

    def get_action(
        self,
        target: TargetAdaptor,
        address: Address,
        relpath: str,
        outgoing_dependency: bool,
    ) -> tuple[VisibilityRuleSet | None, DependencyRuleAction | None, str | None]:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        ruleset = self.get_ruleset(target)
        if ruleset is None:
            return None, None, None
        path = str(address) if address.is_file_target else address.spec_path
        for visibility_rule in ruleset.rules:
            if visibility_rule.match(path, relpath):
                if visibility_rule.action != DependencyRuleAction.ALLOW:
                    target_addr = f"{relpath}:{target.name or os.path.basename(relpath)}"
                    target_type = target.type_alias
                    if outgoing_dependency:
                        logger.debug(
                            f"{visibility_rule.action.name}: the `{target_type}` target "
                            f"{target_addr} dependency to a target at {path} by dependency rule "
                            f"{str(visibility_rule)!r} declared in {self.path}"
                        )
                    else:
                        logger.debug(
                            f"{visibility_rule.action.name}: dependency on the `{target_type}` "
                            f"target {target_addr} from a target at {path} by dependent rule "
                            f"{str(visibility_rule)!r} declared in {self.path}"
                        )
                return ruleset, visibility_rule.action, str(visibility_rule)
        return ruleset, None, None

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
            self.rulesets = [VisibilityRuleSet.parse(build_file, arg) for arg in args if arg]
            self.path = build_file
        except ValueError as e:
            raise BuildFileVisibilityRulesError(f"{build_file}: {e}") from e

        if extend and self.parent:
            self.rulesets.extend(self.parent.rulesets)
