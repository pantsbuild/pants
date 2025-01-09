# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
import os.path
from dataclasses import dataclass, field
from pathlib import PurePath
from pprint import pformat
from typing import Any, Iterable, Iterator, Sequence, cast

from pants.backend.visibility.glob import TargetGlob
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
            pformat((tuple(map(str, ruleset.selectors)), *map(str, ruleset.rules), "!*"))
            if ruleset is not None
            else '(<target selector(s)>, <rule(s), ...>, "!*"),'
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
    glob: TargetGlob

    @classmethod
    def parse(
        cls,
        rule: str | dict,
        relpath: str,
    ) -> VisibilityRule:
        pattern: str | dict
        if isinstance(rule, str):
            if rule.startswith("!"):
                action = DependencyRuleAction.DENY
                pattern = rule[1:]
            elif rule.startswith("?"):
                action = DependencyRuleAction.WARN
                pattern = rule[1:]
            else:
                action = DependencyRuleAction.ALLOW
                pattern = rule
        elif isinstance(rule, dict):
            action = DependencyRuleAction(rule.get("action", "allow"))
            pattern = rule
        else:
            raise ValueError(f"invalid visibility rule: {rule!r}")
        return cls(action, TargetGlob.parse(pattern, relpath))

    def match(self, address: Address, adaptor: TargetAdaptor, relpath: str) -> bool:
        return self.glob.match(address, adaptor, relpath)

    def __str__(self) -> str:
        prefix = ""
        if self.action is DependencyRuleAction.DENY:
            prefix = "!"
        elif self.action is DependencyRuleAction.WARN:
            prefix = "?"
        return f"{prefix}{self.glob}"


def flatten(xs, *types: type) -> Iterator:
    """Return an iterator with values, regardless of the nesting of the input."""
    assert types
    if str in types and isinstance(xs, str):
        yield from (x.strip() for x in xs.splitlines())
    elif isinstance(xs, types):
        yield xs
    elif isinstance(xs, Iterable):
        yield from itertools.chain.from_iterable(flatten(x, *types) for x in xs)
    elif isinstance(xs, PurePath):
        yield str(xs)
    elif type(xs).__name__ == "Registrar":
        yield f"<{xs}>"
    else:
        raise ValueError(f"expected {' or '.join(typ.__name__ for typ in types)} but got: {xs!r}")


@dataclass(frozen=True)
class VisibilityRuleSet:
    """An ordered set of rules that applies to some set of target types."""

    build_file: str
    selectors: tuple[TargetGlob, ...]
    rules: tuple[VisibilityRule, ...]

    def __post_init__(self) -> None:
        if all("!*" == str(selector) for selector in self.selectors):
            rules = tuple(map(str, self.rules))
            raise BuildFileVisibilityRulesError(
                softwrap(
                    f"""
                    The rule set will never apply to anything, for the rules: {rules}

                    At least one target selector must have a filtering rule that can match
                    something, for example:

                        ("<python_*>", {rules})
                    """
                )
            )

    @classmethod
    def parse(cls, build_file: str, arg: Any) -> VisibilityRuleSet:
        """Translate input `arg` from BUILD file call.

        The arg is a rule spec tuple with two or more elements, where the first is the target
        selector(s) and the rest are target rules.
        """
        if not isinstance(arg, Sequence) or isinstance(arg, str) or len(arg) < 2:
            raise ValueError(
                "Invalid rule spec, expected (<target selector(s)>, <rule(s)>, <rule(s)>, ...) "
                f"but got: {arg!r}"
            )

        relpath = os.path.dirname(build_file)
        try:
            selectors = cast("Iterator[str | dict]", flatten(arg[0], str, dict))
            rules = cast("Iterator[str | dict]", flatten(arg[1:], str, dict))
            return cls(
                build_file,
                tuple(TargetGlob.parse(selector, relpath) for selector in selectors),
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

    def peek(self) -> tuple[str, ...]:
        return tuple(map(str, self.rules))

    @staticmethod
    def _noop_rule(rule: str | dict) -> bool:
        return not rule or isinstance(rule, str) and rule.startswith("#")

    def match(self, address: Address, adaptor: TargetAdaptor, relpath: str) -> bool:
        return any(selector.match(address, adaptor, relpath) for selector in self.selectors)


@dataclass(frozen=True)
class BuildFileVisibilityRules(BuildFileDependencyRules):
    path: str
    rulesets: tuple[VisibilityRuleSet, ...]

    @staticmethod
    def create_parser_state(
        path: str, parent: BuildFileDependencyRules | None
    ) -> BuildFileDependencyRulesParserState:
        return BuildFileVisibilityRulesParserState(path, cast(BuildFileVisibilityRules, parent))

    @classmethod
    def check_dependency_rules(
        cls,
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
                address=origin_address,
                adaptor=origin_adaptor,
                other_address=dependency_address,
                other_adaptor=dependency_adaptor,
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
                address=dependency_address,
                adaptor=dependency_adaptor,
                other_address=origin_address,
                other_adaptor=origin_adaptor,
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

    @staticmethod
    def _get_address_relpath(address: Address) -> str:
        if address.is_file_target:
            return os.path.dirname(address.filename)
        return address.spec_path

    @staticmethod
    def _get_address_path(address: Address) -> str:
        return TargetGlob.address_path(address)

    def get_action(
        self,
        address: Address,
        adaptor: TargetAdaptor,
        other_address: Address,
        other_adaptor: TargetAdaptor,
    ) -> tuple[VisibilityRuleSet | None, DependencyRuleAction | None, str | None]:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        relpath = self._get_address_relpath(address)
        ruleset = self.get_ruleset(address, adaptor, relpath)
        if ruleset is None:
            return None, None, None
        for visibility_rule in ruleset.rules:
            if visibility_rule.match(other_address, other_adaptor, relpath):
                if visibility_rule.action != DependencyRuleAction.ALLOW:
                    path = self._get_address_path(other_address)
                    logger.debug(
                        softwrap(
                            f"""
                            {visibility_rule.action.name}: type={adaptor.type_alias}
                            address={address} [{relpath}] other={other_address} [{path}]
                            rule={str(visibility_rule)!r} {self.path}:
                            {', '.join(map(str, ruleset.rules))}
                            """
                        )
                    )
                return ruleset, visibility_rule.action, str(visibility_rule)
        return ruleset, None, None

    def get_ruleset(
        self, address: Address, target: TargetAdaptor, relpath: str | None = None
    ) -> VisibilityRuleSet | None:
        if relpath is None:
            relpath = self._get_address_relpath(address)
        for ruleset in self.rulesets:
            if ruleset.match(address, target, relpath):
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
        if self.rulesets:
            raise BuildFileVisibilityRulesError(
                softwrap(
                    """
                    There must be at most one each of the `__dependencies_rules__()` /
                    `__dependents_rules__()` declarations per BUILD file.

                    To declare multiple rule sets, simply provide them in a single call.

                    Example:

                      __dependencies_rules__(
                        (
                           (files, resources),
                           "//resources/**",
                           "//files/**",
                           "!*",
                        ),
                        (
                          python_sources,
                          "//src/**",
                          "!*",
                        ),
                        ("*", "*"),
                      )
                    """
                )
            )

        try:
            self.rulesets = [VisibilityRuleSet.parse(build_file, arg) for arg in args if arg]
            self.path = build_file
        except ValueError as e:
            raise BuildFileVisibilityRulesError(str(e)) from e

        if extend and self.parent:
            self.rulesets.extend(self.parent.rulesets)
