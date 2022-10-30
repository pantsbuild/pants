# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import ClassVar, Iterable, Literal, Mapping, Tuple, Union, cast

from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict

SetVisibilityValueT = Tuple[str, ...]
SetVisibilityKeyT = Union[str, Tuple[str, ...]]
SetVisibilityT = Mapping[SetVisibilityKeyT, SetVisibilityValueT]


class VisibilityAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"


SetDefaultVisibilityT = Union[Literal["allow"], Literal["deny"], Literal["warn"]]


@dataclass(frozen=True)
class VisibilityRule:
    action: VisibilityAction
    pattern: str

    @classmethod
    def parse(cls, rule: str) -> VisibilityRule:
        if rule.startswith("!"):
            action = VisibilityAction.DENY
            pattern = rule[1:]
        elif rule.startswith("?"):
            action = VisibilityAction.WARN
            pattern = rule[1:]
        else:
            action = VisibilityAction.ALLOW
            pattern = rule
        return cls(action, pattern)

    def match(self, path: str, relpath: str) -> bool:
        pattern = relpath if self.pattern == "." else self.pattern
        if pattern.startswith("./"):
            pattern = relpath + pattern[1:]
        return fnmatch(path, pattern)


VisibilityRules = Tuple[VisibilityRule, ...]


@dataclass(frozen=True)
class BuildFileVisibility:
    rule_class: ClassVar[type[VisibilityRule]] = VisibilityRule

    default: VisibilityAction
    all: VisibilityRules
    targets: FrozenDict[str, VisibilityRules]

    @classmethod
    def create(
        cls,
        default: SetDefaultVisibilityT = "allow",
        all: Iterable[str] = (),
        targets: Mapping[str, Iterable[str]] = {},
    ) -> BuildFileVisibility:
        return cls(
            VisibilityAction(default),
            cls.parse_visibility_rules(all),
            FrozenDict(
                {
                    type_alias: cls.parse_visibility_rules(rules)
                    for type_alias, rules in targets.items()
                }
            ),
        )

    @classmethod
    def parse_visibility_rules(cls, rules: Iterable[str]) -> VisibilityRules:
        return tuple(map(cls.rule_class.parse, rules))

    def get_rules(self, type_alias: str) -> VisibilityRules:
        if type_alias in self.targets:
            return self.targets[type_alias]
        else:
            return self.all

    def get_action(self, type_alias: str, path: str, relpath: str) -> VisibilityAction:
        for visibility_rule in self.get_rules(type_alias):
            if visibility_rule.match(path, relpath):
                return visibility_rule.action
        return self.default

    @staticmethod
    def check_visibility(
        *,
        source_type: str,
        source_path: str,
        dependencies_visibility: BuildFileVisibility,
        target_type: str,
        target_path: str,
        dependents_visibility: BuildFileVisibility,
    ) -> VisibilityAction:
        """The source of the dependency has the dependencies field, the target of the dependency is
        the one listed as a value in the dependencies field.

        The `__dependencies_visibility__` are the rules applicable for the source path.
        The `__dependents_visibility__` are the rules applicable for the target path.

        Return visibility action ALLOW, DENY or WARN. WARN is effectively the same as ALLOW, but
        with a logged warning.
        """
        # Check outgoing dependency action
        outgoing = dependencies_visibility.get_action(source_type, target_path, relpath=source_path)
        if outgoing == VisibilityAction.DENY:
            return outgoing
        # Check incoming dependency action
        incoming = dependents_visibility.get_action(target_type, source_path, relpath=target_path)
        return incoming if incoming != VisibilityAction.ALLOW else outgoing


@dataclass
class BuildFileVisibilityParserState:
    parent: BuildFileVisibility | None
    default: VisibilityAction = VisibilityAction.ALLOW
    all: VisibilityRules = ()
    targets: dict[str, VisibilityRules] = field(default_factory=dict)
    build_file_visibility_class: type[BuildFileVisibility] | None = BuildFileVisibility

    def get_frozen_visibility(self) -> BuildFileVisibility | None:
        if self.build_file_visibility_class is None:
            return None
        else:
            return self.build_file_visibility_class(
                default=self.default, all=self.all, targets=FrozenDict(self.targets)
            )

    def set_visibility(
        self,
        build_file: str,
        *args: SetVisibilityT,
        all: SetVisibilityValueT | None = None,
        default: SetDefaultVisibilityT | None = None,
        extend: bool = False,
        **kwargs,
    ) -> None:
        if self.build_file_visibility_class is None:
            return None

        if all is not None:
            self.all = self._process_visibility(all, build_file)
        elif extend and self.parent is not None:
            self.all = self.parent.all

        if default is not None:
            self.default = VisibilityAction(default)
        elif extend and self.parent is not None:
            self.default = self.parent.default

        visibility: dict[str, VisibilityRules] = {}
        if extend and self.parent is not None:
            visibility = dict(self.parent.targets)

        for targets_visibility in args:
            if not isinstance(targets_visibility, dict):
                raise ValueError(
                    f"Expected dictionary mapping targets to visibility rules in {build_file} "
                    f"but got: {type(targets_visibility).__name__}."
                )
            for target, rules in targets_visibility.items():
                targets: Iterable[str]
                targets = target if isinstance(target, tuple) else (target,)
                for type_alias in map(str, targets):
                    visibility[type_alias] = self._process_visibility(rules, build_file)

        # Update with new visibility, dropping targets without any rules.
        for tgt, rules in visibility.items():
            if not rules:
                self.targets.pop(tgt, None)
            else:
                self.targets[tgt] = rules

    def _process_visibility(self, rules: Iterable[str], build_file: str) -> VisibilityRules:
        """Must only be called after ensuring self.build_file_visibility_class != None."""
        if not isinstance(rules, (list, tuple)):
            raise ValueError(
                f"Invalid visibility rule values in {build_file}, "
                f"must be a sequence of strings but was `{type(rules).__name__}`: {rules!r}"
            )

        return cast(
            "type[BuildFileVisibility]", self.build_file_visibility_class
        ).parse_visibility_rules(rules)


@union
class BuildFileVisibilityImplementationRequest:
    pass


@dataclass(frozen=True)
class BuildFileVisibilityImplementation:
    build_file_visibility_class: type[BuildFileVisibility]


@dataclass(frozen=True)
class MaybeBuildFileVisibilityImplementation:
    build_file_visibility_class: type[BuildFileVisibility] | None


@rule
async def get_build_file_visibility_implementation(
    union_membership: UnionMembership,
) -> MaybeBuildFileVisibilityImplementation:
    request_types = union_membership.get(BuildFileVisibilityImplementationRequest)
    assert len(request_types) <= 1  # TODO: provide proper error message in case of multiple
    # visibility implementations.
    for request_type in request_types:
        impl = await Get(
            BuildFileVisibilityImplementation,
            BuildFileVisibilityImplementationRequest,
            request_type(),
        )
        return MaybeBuildFileVisibilityImplementation(impl.build_file_visibility_class)
    return MaybeBuildFileVisibilityImplementation(None)


def rules():
    return collect_rules()
