# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from typing_extensions import Protocol

from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


class DependencyRulesError(Exception):
    pass


class DependencyRuleActionDeniedError(DependencyRulesError):
    @classmethod
    def create(cls, description_of_origin: str) -> DependencyRuleActionDeniedError:
        return cls(f"Dependency rule violation for {description_of_origin}")


class DependencyRuleAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"

    def execute(
        self, *, description_of_origin: str, return_exc: bool = False
    ) -> DependencyRuleActionDeniedError | None:
        if self is DependencyRuleAction.ALLOW:
            return None
        err = DependencyRuleActionDeniedError.create(description_of_origin)
        if self is DependencyRuleAction.DENY:
            if return_exc:
                return err
            else:
                raise err
        if self is DependencyRuleAction.WARN:
            logger.warning(str(err))
        else:
            raise NotImplementedError(f"{type(self).__name__}.execute() not implemented for {self}")
        return None

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class DependencyRuleApplication:
    action: DependencyRuleAction
    rule_description: str
    origin_address: Address
    origin_type: str
    dependency_address: Address
    dependency_type: str

    def execute(self) -> str | None:
        err = self.action.execute(
            description_of_origin=(
                f"{self.origin_address}'s dependency on {self.dependency_address}"
            ),
            return_exc=True,
        )
        if err is None:
            return None
        else:
            return str(self)

    def __str__(self) -> str:
        return (
            f"{self.rule_description} : {self.action.name}\n{self.origin_type} "
            f"{self.origin_address} -> {self.dependency_type} {self.dependency_address}"
        )


class DependencyRuleSet(Protocol):
    def peek(self) -> tuple[str, ...]:
        """Return a list of all rules in rule set."""


class BuildFileDependencyRules(ABC):
    @staticmethod
    @abstractmethod
    def create_parser_state(
        path: str, parent: BuildFileDependencyRules | None
    ) -> BuildFileDependencyRulesParserState:
        ...

    @staticmethod
    @abstractmethod
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

    @abstractmethod
    def get_ruleset(self, address: Address, target: TargetAdaptor) -> DependencyRuleSet | None:
        ...


class BuildFileDependencyRulesParserState(ABC):
    @abstractmethod
    def get_frozen_dependency_rules(self) -> BuildFileDependencyRules | None:
        pass

    @abstractmethod
    def set_dependency_rules(
        self,
        build_file: str,
        *args,
        **kwargs,
    ) -> None:
        pass


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
        impl = await Get(  # noqa: PNT30: this for loop will never process more than a single iteration.
            BuildFileDependencyRulesImplementation,
            BuildFileDependencyRulesImplementationRequest,
            request_type(),
        )
        return MaybeBuildFileDependencyRulesImplementation(impl.build_file_dependency_rules_class)
    return MaybeBuildFileDependencyRulesImplementation(None)


def rules():
    return collect_rules()
