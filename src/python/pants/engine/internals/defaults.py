# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Tuple, Union, cast

from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException, RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict

DefaultFieldValuesT = FrozenDict[str, Any]
DefaultsValueT = FrozenDict[str, DefaultFieldValuesT]
DefaultsT = FrozenDict[str, DefaultsValueT]

SetDefaultFieldValuesT = Mapping[str, Any]
SetDefaultsValueT = Mapping[str, SetDefaultFieldValuesT]
SetDefaultsKeyT = Union[str, Tuple[str, ...]]
SetDefaultsT = Mapping[SetDefaultsKeyT, SetDefaultsValueT]


@dataclass
class BuildFileDefaultsProvider:
    # The defaults for each target from all BUILD files, per rel path.
    defaults: dict[str, BuildFileDefaults] = field(default_factory=dict)

    def get_defaults_for(self, rel_path: str) -> BuildFileDefaults:
        # The BUILD file parsing is executed in order to ensure we don't get a race condition
        # creating defaults here.

        if rel_path in self.defaults:
            return self.defaults[rel_path]

        if rel_path == "":
            return self.defaults.setdefault("", BuildFileDefaults("", FrozenDict(), self))

        parent = os.path.dirname(rel_path)
        return self.defaults.setdefault(
            rel_path, BuildFileDefaults(rel_path, self.get_defaults_for(parent).defaults, self)
        )

    def set_defaults(self, defaults: BuildFileDefaults) -> None:
        self.defaults[defaults.path] = defaults


@dataclass(frozen=True)
class BuildFileDefaults:
    path: str
    defaults: DefaultsT
    provider: BuildFileDefaultsProvider = field(hash=False, compare=False)

    def as_mutable(
        self, registered_target_types: RegisteredTargetTypes, union_membership: UnionMembership
    ) -> MutableBuildFileDefaults:
        return MutableBuildFileDefaults(
            defaults=dict(self.defaults),
            immutable=self,
            registered_target_types=registered_target_types,
            union_membership=union_membership,
        )

    def commit(self) -> None:
        self.provider.set_defaults(self)


@dataclass
class MutableBuildFileDefaults:
    defaults: dict[str, Mapping[str, Any]]
    immutable: BuildFileDefaults
    registered_target_types: RegisteredTargetTypes
    union_membership: UnionMembership

    def commit(self) -> None:
        defaults = replace(self.immutable, defaults=self.freezed_defaults())
        defaults.commit()

    def freezed_defaults(self) -> DefaultsT:
        address = Address(self.immutable.path, generated_name="__defaults__")
        types = self.registered_target_types.aliases_to_types
        return FrozenDict(
            {
                target_alias: FrozenDict(
                    {
                        field_type.alias: field_type.compute_value(
                            raw_value=default, address=address
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
        return self.defaults.get(target_alias, {})

    def set_defaults(self, *args: SetDefaultsT, **kwargs: SetDefaultsValueT) -> None:
        defaults: dict[str, dict[str, Any]] = {}
        types = self.registered_target_types.aliases_to_types
        for target, default in (
            item for arg in (*args, kwargs) for item in cast(SetDefaultsT, arg).items()
        ):
            if not isinstance(default, dict):
                raise ValueError(
                    f"{self.immutable.path}: The default field values passed to __defaults__ for "
                    f"{target} must be a `dict` but got a `{type(default).__name__}`."
                )

            targets: Iterable[str]
            if target == "__all__":
                targets = types.keys()
            else:
                targets = target if isinstance(target, tuple) else (target,)
            for target_alias in targets:
                if target_alias in types:
                    target_type = types[target_alias]
                else:
                    raise ValueError(
                        f"Attempt to set __defaults__ for unknown target type: {target_alias}."
                    )

                # Validate that field exists on target
                target_fields = target_type.class_field_types(self.union_membership)
                valid_field_aliases = set()
                for fld in target_fields:
                    valid_field_aliases.add(fld.alias)
                    if fld.deprecated_alias is not None:
                        valid_field_aliases.add(fld.deprecated_alias)
                for field_alias in default.keys():
                    if field_alias not in valid_field_aliases:
                        raise InvalidFieldException(
                            f"Unrecognized field `{field_alias}` for target {target_type.alias}. "
                            f"Valid fields are: {', '.join(sorted(valid_field_aliases))}.",
                        )
                # TODO: moved fields for TargetGenerators ?  See: `Target._calculate_field_values()`.

                # Merge all provided defaults for this call.
                defaults.setdefault(target_type.alias, {}).update(default)

        # Replace any inherited defaults with the new set of defaults.
        self.defaults.update(defaults)
