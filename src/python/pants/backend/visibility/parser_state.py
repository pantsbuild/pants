# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, cast

from pants.backend.visibility.rule_types import BuildFileVisibilityRulesError, VisibilityRuleSet
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRuleAction,
)
from pants.engine.internals.target_adaptor import TargetAdaptor


@dataclass(frozen=True)
class BuildFileVisibilityRules(BuildFileDependencyRules):
    path: str
    rulesets: Sequence[VisibilityRuleSet]

    @staticmethod
    def create_parser_state(
        path: str, parent: BuildFileDependencyRules | None
    ) -> BuildFileDependencyRulesParserState:
        return BuildFileVisibilityRulesParserState(path, parent)

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
            )
            if dependencies_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if outgoing is None:
            raise BuildFileVisibilityRulesError(
                f"Missing rule for dependency {source_adaptor} {source_path} -> {target_adaptor} {target_path}"
            )
        if outgoing == DependencyRuleAction.DENY:
            return outgoing

        # Check incoming dependency action
        incoming = (
            cast(BuildFileVisibilityRules, dependents_rules).get_action(
                target_adaptor,
                source_path,
                relpath=target_path,
            )
            if dependents_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if incoming is None:
            raise BuildFileVisibilityRulesError(
                f"Missing rule for dependent {target_adaptor} {target_path} -> {source_adaptor} {source_path}"
            )
        return incoming if incoming != DependencyRuleAction.ALLOW else outgoing

    def get_action(
        self, target: TargetAdaptor, path: str, relpath: str
    ) -> DependencyRuleAction | None:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        ruleset = self.get_ruleset(target)
        if ruleset is None:
            return None
        for visibility_rule in ruleset.rules:
            if visibility_rule.match(path, relpath):
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
    parent: BuildFileDependencyRules | None
    rulesets: list[VisibilityRuleSet] = field(default_factory=list)

    def get_frozen_dependency_rules(self) -> BuildFileDependencyRules | None:
        if not self.rulesets:
            return None
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
            self.rulesets = [VisibilityRuleSet.parse(arg) for arg in args]
        except ValueError as e:
            raise BuildFileVisibilityRulesError(f"{build_file}: {e}") from e

        if extend and self.parent:
            self.rulesets.extend(self.parent.rulesets)  # type: ignore[attr-defined]
