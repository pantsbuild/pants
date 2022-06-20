# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Tuple, Union

from pants.engine.addresses import Address
from pants.engine.target import ImmutableValue, InvalidFieldException, RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict

SetDefaultsValueT = Mapping[str, Any]
SetDefaultsKeyT = Union[str, Tuple[str, ...]]
SetDefaultsT = Mapping[SetDefaultsKeyT, SetDefaultsValueT]


@dataclass
class BuildFileDefaultsProvider:
    registered_target_types: RegisteredTargetTypes
    union_membership: UnionMembership

    def get_parser_defaults(
        self, path: str, defaults: BuildFileDefaults
    ) -> BuildFileDefaultsParserState:
        return BuildFileDefaultsParserState(
            address=Address(path, generated_name="__defaults__"),
            defaults=dict(defaults),
            provider=self,
        )


class BuildFileDefaults(FrozenDict[str, FrozenDict[str, ImmutableValue]]):
    """Map target types to default field values."""


@dataclass
class BuildFileDefaultsParserState:
    address: Address
    defaults: dict[str, Mapping[str, Any]]
    provider: BuildFileDefaultsProvider

    @property
    def registered_target_types(self) -> RegisteredTargetTypes:
        return self.provider.registered_target_types

    @property
    def union_membership(self) -> UnionMembership:
        return self.provider.union_membership

    def freezed_defaults(self) -> BuildFileDefaults:
        types = self.registered_target_types.aliases_to_types
        return BuildFileDefaults(
            {
                target_alias: FrozenDict(
                    {
                        field_type.alias: field_type.compute_value(
                            raw_value=default, address=self.address
                        )
                        for field_alias, default in fields.items()
                        for field_type in types[target_alias].class_field_types(
                            self.union_membership
                        )
                        if field_alias in (field_type.alias, field_type.deprecated_alias)
                    }
                )
                for target_alias, fields in self.defaults.items()
            }
        )

    def get(self, target_alias: str) -> Mapping[str, Any]:
        # Used by `pants.engine.internals.parser.Parser._generate_symbols.Registrar.__call__`
        return self.defaults.get(target_alias, {})

    def set_defaults(
        self,
        *args: SetDefaultsT,
        all: SetDefaultsValueT | None = None,
        extend: bool = False,
        **kwargs,
    ) -> None:
        defaults: dict[str, dict[str, Any]] = (
            {} if not extend else {k: dict(v) for k, v in self.defaults.items()}
        )

        if all is not None:
            self._process_defaults(
                defaults,
                {tuple(self.registered_target_types.aliases): all},
                ignore_unknown_fields=True,
            )

        for arg in args:
            self._process_defaults(defaults, arg)

        # Update with new defaults, dropping targets without any default values.
        for tgt, default in defaults.items():
            if not default:
                self.defaults.pop(tgt, None)
            else:
                self.defaults[tgt] = default

    def _process_defaults(
        self,
        defaults: dict[str, dict[str, Any]],
        targets_defaults: SetDefaultsT,
        ignore_unknown_fields: bool = False,
    ):
        if not isinstance(targets_defaults, dict):
            raise ValueError(
                f"Expected dictionary mapping targets to default field values for {self.address} "
                f"but got: {type(targets_defaults).__name__}."
            )

        types = self.registered_target_types.aliases_to_types
        for target, default in targets_defaults.items():
            if not isinstance(default, dict):
                raise ValueError(
                    f"Invalid default field values in {self.address} for target type {target}, "
                    f"must be an `dict` but was {default!r} with type `{type(default).__name__}`."
                )

            targets: Iterable[str]
            targets = target if isinstance(target, tuple) else (target,)
            for target_alias in map(str, targets):
                if target_alias in types:
                    target_type = types[target_alias]
                else:
                    raise ValueError(f"Unrecognized target type {target_alias} in {self.address}.")

                # Copy default dict if we may mutate it.
                raw_values = dict(default) if ignore_unknown_fields else default

                # Validate that field exists on target
                target_fields = target_type.class_field_types(self.union_membership)
                valid_field_aliases = set()

                # TODO: this valid aliases calculation is done every time a target is instantiated
                # as well. But it should be enough to do once, and re-use as it doesn't change
                # during a run.
                for fld in target_fields:
                    valid_field_aliases.add(fld.alias)
                    if fld.deprecated_alias is not None:
                        valid_field_aliases.add(fld.deprecated_alias)

                for field_alias in default.keys():
                    if field_alias not in valid_field_aliases:
                        if ignore_unknown_fields:
                            del raw_values[field_alias]
                        else:
                            raise InvalidFieldException(
                                f"Unrecognized field `{field_alias}` for target {target_type.alias}. "
                                f"Valid fields are: {', '.join(sorted(valid_field_aliases))}.",
                            )
                # TODO: moved fields for TargetGenerators ?  See: `Target._calculate_field_values()`.
                # TODO: support parametrization ?

                # Merge all provided defaults for this call.
                defaults.setdefault(target_type.alias, {}).update(raw_values)
