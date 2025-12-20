# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast

from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.engine.environment import EnvironmentName
from pants.engine.internals.native_engine import Address, Field
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

# NB: This TypeVar serves the same purpose here as in pants.engine.target
_F = TypeVar("_F", bound=Field)


@dataclass(frozen=True)
class InjectedNfpmPackageFields:
    """The injected fields that should be used instead of the target's fields.

    Though any field can technically be provided (except "scripts" which is banned),
    only nfpm package metadata fields will have an impact. Passing other fields are
    silently ignored. For example, "dependencies", and "output_path" are not used
    when generating nfpm config, so they will be ignored; "sources" is not a valid
    field for nfpm package targets, so it will also be ignored.

    The "scripts" field is special in that it has dependency inference tied to it.
    If you write your own dependency inference rule (possibly based on a custom
    field you've added to the nfpm package target), then you can pass
    _allow_banned_fields=True to allow injection of the "scripts" field.
    """

    field_values: FrozenDict[type[Field], Field]

    def __init__(
        self,
        fields: Iterable[Field],
        *,
        address: Address,
        _allow_banned_fields: bool = False,
    ) -> None:
        super().__init__()
        if not _allow_banned_fields:
            aliases = [field.alias for field in fields]
            for alias in {
                NfpmPackageScriptsField.alias,  # if _allow_banned_fields, the plugin author must handle scripts deps.
            }:
                if alias in aliases:
                    raise ValueError(
                        softwrap(
                            f"""
                            {alias} cannot be an injected nfpm package field for {address} to avoid
                            breaking dependency inference.
                            """
                        )
                    )
        # Ignore any fields that do not have a value (assuming nfpm fields have 'none_is_valid_value=False').
        field_values = {type(field): field for field in fields if field.value is not None}
        object.__setattr__(
            self,
            "field_values",
            FrozenDict(
                sorted(
                    field_values.items(),
                    key=lambda field_type_to_val_pair: field_type_to_val_pair[0].alias,
                )
            ),
        )


class _PrioritizedSortableClassMetaclass(ABCMeta):
    """This metaclass implements prioritized sorting of subclasses (not class instances)."""

    priority: ClassVar[int]

    def __lt__(self, other: Any) -> bool:
        """Determine if this class is lower priority than `other` (when chaining request rules).

        The rule that runs the lowest priority request goes first, and the rule that runs the
        highest priority request goes last. The results (the `injected_fields`) of lower priority
        rules can be overridden by higher priority rules. The last rule to run, the rule for the
        highest priority request class, can override any of the fields injected by lower priority
        request rules.
        """
        if not isinstance(other, _PrioritizedSortableClassMetaclass):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority < other.priority
        # other has same priority: fall back to name comparison (ensures deterministic sort)
        return (self.__module__, self.__qualname__) < (other.__module__, other.__qualname__)


# Note: This only exists as a hook for additional logic for nFPM config generation, e.g. for plugin
# authors. To resolve `InjectedNfpmPackageFields`, call `determine_injected_nfpm_package_fields`,
# which handles running any custom implementations vs. using the default implementation.
@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class InjectNfpmPackageFieldsRequest(ABC, metaclass=_PrioritizedSortableClassMetaclass):
    """A request to inject nFPM config for nfpm_package_* targets.

    By default, Pants will use the nfpm_package_* fields in the BUILD file unchanged to generate the
    nfpm.yaml config file for nFPM. To customize this, subclass `InjectNfpmPackageFieldsRequest`,
    register `UnionRule(InjectNfpmPackageFieldsRequest, MyCustomInjectNfpmPackageFieldsRequest)`,
    and add a rule that takes your subclass as a parameter and returns `InjectedNfpmPackageFields`.

    The `target` attribute of this class holds the original target as defined in BUILD files.
    The `injected_fields` attribute of this class contains the results of any previous rule.
    `injected_fields` will be empty for the first rule in the chain. Subsequent rules can remove
    or replace fields injected by previous rules. The final rule in the chain returns the final
    `InjectedNfpmPackageFields` instance that is used to actually generate the nfpm config.
    In general, rules should include a copy of `request.injected_fields` in their return value
    with something like this:

        address = request.target.address
        fields: list[Field] = list(request.injected_fields.values())
        fields.append(NfpmFoobarField("foobar", address))
        return InjectedNfpmPackageFields(fields, address=address)

    Chaining rules like this allows pants to inject some fields, while allowing in-repo plugins
    to override or remove them.
    """

    target: Target
    injected_fields: FrozenDict[type[Field], Field]

    # Classes in pants-provided backends should be priority<10 so that in-repo and external
    # plugins are higher priority by default. This way, the fields that get injected by default
    # can be overridden as needed in the in-repo or external plugins.
    priority: ClassVar[int] = 10

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.priority == getattr(super(), "priority", cls.priority):
            # subclasses are higher priority than their parent class (unless set otherwise).
            cls.priority += 1

    @classmethod
    @abstractmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether to use this InjectNfpmPackageFieldsRequest implementation for this target."""

    def get_field(self, field: type[_F]) -> _F:
        """Get a `Field` from `injected_fields` (returned by earlier rules) or from the target.

        This will throw a KeyError if the `Field` is not registered on the target (unless an earlier
        rule added it to `injected_fields` which might be disallowed in the future).
        """
        if field in self.injected_fields:
            return cast(_F, self.injected_fields[field])
        return self.target[field]


@rule(polymorphic=True)
async def inject_nfpm_package_fields(
    req: InjectNfpmPackageFieldsRequest, env_name: EnvironmentName
) -> InjectedNfpmPackageFields:
    raise NotImplementedError()


@dataclass(frozen=True)
class NfpmPackageTargetWrapper:
    """Nfpm Package target Wrapper.

    This is not meant to be used by plugin authors.
    """

    target: Target


@rule
async def determine_injected_nfpm_package_fields(
    wrapper: NfpmPackageTargetWrapper, union_membership: UnionMembership
) -> InjectedNfpmPackageFields:
    target = wrapper.target
    inject_nfpm_config_request_types = union_membership.get(InjectNfpmPackageFieldsRequest)

    # Requests are sorted (w/ priority ClassVar) before chaining the rules that take them.
    applicable_inject_nfpm_config_request_types = tuple(
        sorted(
            request_type
            for request_type in inject_nfpm_config_request_types
            if request_type.is_applicable(target)
        )
    )

    # If no provided implementations, fall back to our default implementation that simply returns
    # what the user explicitly specified in the BUILD file.
    if not applicable_inject_nfpm_config_request_types:
        return InjectedNfpmPackageFields((), address=target.address)

    injected: InjectedNfpmPackageFields
    injected_fields: FrozenDict[type[Field], Field] = FrozenDict()
    for request_type in applicable_inject_nfpm_config_request_types:
        chained_request: InjectNfpmPackageFieldsRequest = request_type(target, injected_fields)  # type: ignore[abstract]
        injected = await inject_nfpm_package_fields(
            **implicitly({chained_request: InjectNfpmPackageFieldsRequest})
        )
        injected_fields = injected.field_values

    # return the last result in the chain of results
    return injected


def rules():
    return [
        *collect_rules(),
    ]
