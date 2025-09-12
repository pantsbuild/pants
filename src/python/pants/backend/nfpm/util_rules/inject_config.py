# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.engine.environment import EnvironmentName
from pants.engine.internals.native_engine import Address, Field
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


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


# Note: This only exists as a hook for additional logic for nFPM config generation, e.g. for plugin
# authors. To resolve `InjectedNfpmPackageFields`, call `determine_injected_nfpm_package_fields`,
# which handles running any custom implementations vs. using the default implementation.
@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class InjectNfpmPackageFieldsRequest(ABC):
    """A request to inject nFPM config for nfpm_package_* targets.

    By default, Pants will use the nfpm_package_* fields in the BUILD file unchanged to generate the
    nfpm.yaml config file for nFPM. To customize this, subclass `InjectNfpmPackageFieldsRequest`,
    register `UnionRule(InjectNfpmPackageFieldsRequest, MyCustomInjectNfpmPackageFieldsRequest)`,
    and add a rule that takes your subclass as a parameter and returns `InjectedNfpmPackageFields`.
    """

    target: Target

    @classmethod
    @abstractmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether to use this InjectNfpmPackageFieldsRequest implementation for this target."""


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
    inject_nfpm_config_requests = union_membership.get(InjectNfpmPackageFieldsRequest)
    applicable_inject_nfpm_config_requests = tuple(
        request for request in inject_nfpm_config_requests if request.is_applicable(target)
    )

    # If no provided implementations, fall back to our default implementation that simply returns
    # what the user explicitly specified in the BUILD file.
    if not applicable_inject_nfpm_config_requests:
        return InjectedNfpmPackageFields((), address=target.address)

    if len(applicable_inject_nfpm_config_requests) > 1:
        possible_requests = sorted(
            plugin.__name__ for plugin in applicable_inject_nfpm_config_requests
        )
        raise ValueError(
            softwrap(
                f"""
                Multiple registered `InjectNfpmPackageFieldsRequest`s can work on the target
                {target.address}, and it's ambiguous which to use: {possible_requests}

                Please activate fewer implementations, or make the classmethod `is_applicable()`
                more precise so that only one implementation is applicable for this target.
                """
            )
        )
    inject_nfpm_config_request_type = applicable_inject_nfpm_config_requests[0]
    inject_nfpm_config_request: InjectNfpmPackageFieldsRequest = inject_nfpm_config_request_type(
        target
    )  # type: ignore[abstract]
    return await inject_nfpm_package_fields(
        **implicitly({inject_nfpm_config_request: InjectNfpmPackageFieldsRequest})
    )


def rules():
    return [
        *collect_rules(),
    ]
