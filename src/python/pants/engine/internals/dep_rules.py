# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence, Tuple, Union

from typing_extensions import Literal

from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


SetDependencyRulesValueT = Tuple[str, ...]
SetDependencyRulesKeyT = Union[str, Tuple[str, ...]]
SetDependencyRulesT = Mapping[SetDependencyRulesKeyT, SetDependencyRulesValueT]


class DependencyRulesError(Exception):
    pass


class DependencyRuleActionDeniedError(DependencyRulesError):
    pass


class DependencyRuleAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"

    def execute(self, *, description_of_origin: str) -> None:
        if self is DependencyRuleAction.ALLOW:
            return
        msg = f"Dependency rule violation for {description_of_origin}"
        if self is DependencyRuleAction.DENY:
            raise DependencyRuleActionDeniedError(msg)
        if self is DependencyRuleAction.WARN:
            logger.warning(msg)


SetDefaultDependencyRulesT = Union[Literal["allow"], Literal["deny"], Literal["warn"]]


class DependencyRule:
    pass


DependencyRules = Tuple[DependencyRule, ...]


class BuildFileDependencyRules(ABC):
    default: DependencyRuleAction
    all: DependencyRules
    targets: Mapping[str, DependencyRules]

    @classmethod
    @abstractmethod
    def create(
        cls,
        default: DependencyRuleAction = DependencyRuleAction.ALLOW,
        all: Iterable[str | DependencyRule] = (),
        targets: Mapping[str, Iterable[str | DependencyRule]] = {},
    ) -> BuildFileDependencyRules:
        ...

    @staticmethod
    @abstractmethod
    def check_dependency_rules(
        *,
        source_type: str,
        source_path: str,
        dependencies_rules: BuildFileDependencyRules | None,
        target_type: str,
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


@dataclass
class BuildFileDependencyRulesParserState:
    parent: BuildFileDependencyRules | None
    default: DependencyRuleAction = DependencyRuleAction.ALLOW
    all: Sequence[str | DependencyRule] = ()
    targets: dict[str, Sequence[str | DependencyRule]] = field(default_factory=dict)
    build_file_dependency_rules_class: type[BuildFileDependencyRules] | None = None

    def get_frozen_dependency_rules(self) -> BuildFileDependencyRules | None:
        if self.build_file_dependency_rules_class is None:
            return None
        else:
            return self.build_file_dependency_rules_class.create(
                default=self.default, all=self.all, targets=self.targets
            )

    def set_dependency_rules(
        self,
        build_file: str,
        *args: SetDependencyRulesT,
        all: SetDependencyRulesValueT | None = None,
        default: SetDefaultDependencyRulesT | None = None,
        extend: bool = False,
        **kwargs,
    ) -> None:
        if self.build_file_dependency_rules_class is None:
            return None

        if all is not None:
            self.all = self._check_rules(all, build_file)
        elif extend and self.parent is not None:
            self.all = self.parent.all

        if default is not None:
            self.default = DependencyRuleAction(default)
        elif extend and self.parent is not None:
            self.default = self.parent.default

        dependency: dict[str, Sequence[str | DependencyRule]] = {}
        if extend and self.parent is not None:
            dependency = dict(self.parent.targets)

        for targets_dependency in args:
            if not isinstance(targets_dependency, dict):
                raise ValueError(
                    f"Expected dictionary mapping targets to dependency rules in {build_file} "
                    f"but got: {type(targets_dependency).__name__}."
                )
            for target, rules in targets_dependency.items():
                targets: Iterable[str]
                targets = target if isinstance(target, tuple) else (target,)
                for type_alias in map(str, targets):
                    dependency[type_alias] = self._check_rules(rules, build_file)

        # Update with new dependency, dropping targets without any rules.
        for tgt, rules in dependency.items():
            if not rules:
                self.targets.pop(tgt, None)
            else:
                self.targets[tgt] = rules

    def _check_rules(self, rules: Iterable[str], build_file: str) -> tuple[str, ...]:
        """Must only be called after ensuring self.build_file_dependency_rules_class != None."""
        if not isinstance(rules, (list, tuple)):
            raise ValueError(
                f"Invalid dependency rule values in {build_file}, "
                f"must be a sequence of strings but was `{type(rules).__name__}`: {rules!r}"
            )
        return tuple(rules)


@union
class BuildFileDependencyRulesImplementationRequest:
    pass


@dataclass(frozen=True)
class BuildFileDependencyRulesImplementation:
    build_file_dependency_rules_class: type[BuildFileDependencyRules]


@dataclass(frozen=True)
class MaybeBuildFileDependencyRulesImplementation:
    build_file_dependency_rules_class: type[BuildFileDependencyRules] | None


@rule
async def get_build_file_dependency_rules_implementation(
    union_membership: UnionMembership,
) -> MaybeBuildFileDependencyRulesImplementation:
    request_types = union_membership.get(BuildFileDependencyRulesImplementationRequest)
    if len(request_types) > 1:
        impls = ", ".join(map(str, request_types))
        raise AssertionError(
            f"There must be at most one BUILD file dependency rules implementation, got: {impls}"
        )
    for request_type in request_types:
        impl = await Get(
            BuildFileDependencyRulesImplementation,
            BuildFileDependencyRulesImplementationRequest,
            request_type(),
        )
        return MaybeBuildFileDependencyRulesImplementation(impl.build_file_dependency_rules_class)
    return MaybeBuildFileDependencyRulesImplementation(None)


def rules():
    return collect_rules()
