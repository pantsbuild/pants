# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable, Iterator, Mapping, Tuple, cast

from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesImplementation,
    BuildFileDependencyRulesImplementationRequest,
    DependencyRule,
    DependencyRuleAction,
    DependencyRules,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRuleAction,
    DependenciesRuleActionRequest,
    FieldSet,
    ValidatedDependencies,
    ValidateDependenciesRequest,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


class BuildFileVisibilityImplementationRequest(BuildFileDependencyRulesImplementationRequest):
    pass


class VisibilityValidateFieldSet(FieldSet):
    required_fields = (Dependencies,)


class VisibilityValidateDependenciesRequest(ValidateDependenciesRequest):
    field_set_type = VisibilityValidateFieldSet


@dataclass(frozen=True)
class VisibilityRule(DependencyRule):
    action: DependencyRuleAction
    pattern: str

    @classmethod
    def parse(cls, rule: str) -> VisibilityRule:
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
        pattern = relpath if self.pattern == "." else self.pattern
        if pattern.startswith("./"):
            pattern = relpath + pattern[1:]
        return fnmatch(path, pattern)


VisibilityRules = Tuple[VisibilityRule, ...]


@dataclass(frozen=True)
class BuildFileVisibilityRules(BuildFileDependencyRules):
    default: DependencyRuleAction
    all: DependencyRules
    targets: Mapping[str, DependencyRules]

    @classmethod
    def create(
        cls,
        default: DependencyRuleAction = DependencyRuleAction.ALLOW,
        all: Iterable[str | DependencyRule] = (),
        targets: Mapping[str, Iterable[str | DependencyRule]] = {},
    ) -> BuildFileVisibilityRules:
        return cls(
            default,
            cls.parse_visibility_rules(all),
            FrozenDict(
                {
                    type_alias: cls.parse_visibility_rules(rules)
                    for type_alias, rules in targets.items()
                }
            ),
        )

    @classmethod
    def parse_visibility_rules(cls, rules: Iterable[str | DependencyRule]) -> DependencyRules:
        return tuple(
            VisibilityRule.parse(rule) if isinstance(rule, str) else rule for rule in rules
        )

    def get_rules(self, target: TargetAdaptor) -> Iterator[VisibilityRule]:
        if target.type_alias in self.targets:
            yield from cast(VisibilityRules, self.targets[target.type_alias])
        # The `all` rules always apply as fall-through from any target specific rules.
        yield from cast(VisibilityRules, self.all)

    def get_action(self, target: TargetAdaptor, path: str, relpath: str) -> DependencyRuleAction:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        for visibility_rule in self.get_rules(target):
            if visibility_rule.match(path, relpath):
                return visibility_rule.action
        return self.default

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
                source_adaptor, target_path, relpath=source_path
            )
            if dependencies_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if outgoing == DependencyRuleAction.DENY:
            return outgoing
        # Check incoming dependency action
        incoming = (
            cast(BuildFileVisibilityRules, dependents_rules).get_action(
                target_adaptor, source_path, relpath=target_path
            )
            if dependents_rules is not None
            else DependencyRuleAction.ALLOW
        )
        return incoming if incoming != DependencyRuleAction.ALLOW else outgoing


@rule
def build_file_visibility_implementation(
    _: BuildFileVisibilityImplementationRequest,
) -> BuildFileDependencyRulesImplementation:
    return BuildFileDependencyRulesImplementation(BuildFileVisibilityRules)


@rule
async def visibility_validate_dependencies(
    request: VisibilityValidateDependenciesRequest,
) -> ValidatedDependencies:
    address = request.field_set.address
    dependencies_rule_action = await Get(
        DependenciesRuleAction,
        DependenciesRuleActionRequest(
            address=address,
            dependencies=request.dependencies,
            description_of_origin=f"get dependency rules for {address}",
        ),
    )
    dependencies_rule_action.execute_actions()
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(
            BuildFileDependencyRulesImplementationRequest,
            BuildFileVisibilityImplementationRequest,
        ),
        UnionRule(ValidateDependenciesRequest, VisibilityValidateDependenciesRequest),
    )
