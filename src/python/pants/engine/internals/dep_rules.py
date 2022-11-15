# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


class DependencyRulesError(Exception):
    pass


class DependencyRuleActionDeniedError(DependencyRulesError):
    def __init__(self, description_of_origin: str):
        super().__init__(self.violation_msg(description_of_origin))

    def violation_msg(self, description_of_origin: str) -> str:
        return f"Dependency rule violation for {description_of_origin}"


class DependencyRuleAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"

    def execute(self, *, description_of_origin: str) -> None:
        if self is DependencyRuleAction.ALLOW:
            return
        err = DependencyRuleActionDeniedError(description_of_origin)
        if self is DependencyRuleAction.DENY:
            raise err
        if self is DependencyRuleAction.WARN:
            logger.warning(str(err))
        else:
            raise NotImplementedError(f"{type(self).__name__}.execute() not implemented for {self}")


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
        impl = await Get(
            BuildFileDependencyRulesImplementation,
            BuildFileDependencyRulesImplementationRequest,
            request_type(),
        )
        return MaybeBuildFileDependencyRulesImplementation(impl.build_file_dependency_rules_class)
    return MaybeBuildFileDependencyRulesImplementation(None)


def rules():
    return collect_rules()
