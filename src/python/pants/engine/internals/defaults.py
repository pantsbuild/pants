# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""The `BuildFileDefaultsParserState.set_defaults` is used by the pants.engine.internals.Parser,
exposed as the `__defaults__` BUILD file symbol.

When parsing a BUILD (from the rule `pants.engine.internals.build_files.parse_address_family`) the
defaults from the closest parent BUILD file is passed as input to the parser, and the new defaults
resulting after the BUILD file have been parsed is returned in the `AddressFamily`.

These defaults are then applied when creating the `TargetAdaptor` targets by the `Registrar` in the
parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Tuple, Union

from pants.engine.addresses import Address
from pants.engine.internals.parametrize import Parametrize
from pants.engine.target import (
    Field,
    ImmutableValue,
    InvalidFieldException,
    RegisteredTargetTypes,
    Target,
    TargetGenerator,
)
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict

SetDefaultsValueT = Union[Mapping[str, Any], Tuple[Any, ...]]
SetDefaultsKeyT = Union[str, Tuple[str, ...]]
SetDefaultsT = Mapping[SetDefaultsKeyT, SetDefaultsValueT]


@dataclass(frozen=True)
class TargetDefaults:
    args: tuple[ImmutableValue, ...]
    kwargs: FrozenDict[str, ImmutableValue]

    @dataclass
    class Builder:
        target_type: type[Target]
        union_membership: UnionMembership
        args: list[Any] = field(default_factory=list)
        kwargs: dict[str, Any] = field(default_factory=dict)

        @classmethod
        def from_defaults(
            cls,
            defaults: TargetDefaults,
            target_type: type[Target],
            union_membership: UnionMembership,
        ) -> TargetDefaults.Builder:
            return cls(
                args=list(defaults.args),
                kwargs=dict(defaults.kwargs),
                target_type=target_type,
                union_membership=union_membership,
            )

        def to_defaults(self, address: Address) -> TargetDefaults:
            return TargetDefaults(
                args=self._freeze_value(self.args),
                kwargs=FrozenDict(
                    {
                        field_type.alias: self._freeze_field_value(field_type, default, address)
                        for field_alias, default in self.kwargs.items()
                        for field_type in self._field_types()
                        if field_alias in (field_type.alias, field_type.deprecated_alias)
                    }
                ),
            )

        def __bool__(self) -> bool:
            return bool(self.args or self.kwargs)

        def _freeze_value(self, value: Any) -> ImmutableValue:
            if isinstance(value, (list, set)):
                return tuple(map(self._freeze_value, value))
            elif isinstance(value, Parametrize):
                return ParametrizeDefault.create(self._freeze_value, value)
            elif isinstance(value, dict):
                return FrozenDict.deep_freeze(value)
            else:
                return value

        def _freeze_field_value(
            self, field_type: type[Field], value: Any, address: Address
        ) -> ImmutableValue:
            if isinstance(value, ParametrizeDefault):
                return value
            elif isinstance(value, Parametrize):

                def freeze(v: Any) -> ImmutableValue:
                    return self._freeze_field_value(field_type, v, address)

                return ParametrizeDefault.create(freeze, value)
            else:
                return field_type.compute_value(raw_value=value, address=address)

        def _field_types(self) -> tuple[type[Field], ...]:
            return (
                *self.target_type.class_field_types(self.union_membership),
                *(
                    self.target_type.moved_fields
                    if issubclass(self.target_type, TargetGenerator)
                    else ()
                ),
            )

        def update_field_defaults(
            self, defaults: MutableMapping[str, Any], ignore_unknown_fields: bool
        ) -> None:
            # Copy default dict if we may mutate it.
            raw_values = dict(defaults) if ignore_unknown_fields else defaults

            # Validate that field exists on target
            valid_field_aliases = set(
                self.target_type._get_field_aliases_to_field_types(self._field_types()).keys()
            )

            for field_alias in defaults.keys():
                if field_alias not in valid_field_aliases:
                    if ignore_unknown_fields:
                        del raw_values[field_alias]
                    else:
                        raise InvalidFieldException(
                            f"Unrecognized field `{field_alias}` for target {self.target_type.alias}. "
                            f"Valid fields are: {', '.join(sorted(valid_field_aliases))}.",
                        )

            # Merge all provided defaults for this call.
            self.kwargs.update(raw_values)

        def update_args_defaults(self, defaults: Iterable[Any]) -> None:
            self.args.extend(defaults)


class BuildFileDefaults(FrozenDict[str, TargetDefaults]):
    """Map target types to default field values."""


class ParametrizeDefault(Parametrize):
    """Parametrize for default field values.

    This is to have eager validation on the field values rather than erroring first when applied on
    an actual target.
    """

    @classmethod
    def create(
        cls, freeze: Callable[[Any], ImmutableValue], parametrize: Parametrize
    ) -> ParametrizeDefault:
        return cls(
            *map(freeze, parametrize.args),
            **{kw: freeze(arg) for kw, arg in parametrize.kwargs.items()},
        )


@dataclass
class BuildFileDefaultsParserState:
    address: Address
    defaults: dict[str, TargetDefaults]
    registered_target_types: RegisteredTargetTypes
    union_membership: UnionMembership

    @classmethod
    def create(
        cls,
        path: str,
        defaults: BuildFileDefaults,
        registered_target_types: RegisteredTargetTypes,
        union_membership: UnionMembership,
    ) -> BuildFileDefaultsParserState:
        return cls(
            address=Address(path, generated_name="__defaults__"),
            defaults=dict(defaults),
            registered_target_types=registered_target_types,
            union_membership=union_membership,
        )

    def get_frozen_defaults(self) -> BuildFileDefaults:
        return BuildFileDefaults(FrozenDict(self.defaults))

    def get(self, target_alias: str) -> TargetDefaults | None:
        # Used by `pants.engine.internals.parser.Parser._generate_symbols.Registrar.__call__`
        return self.defaults.get(target_alias)

    def set_defaults(
        self,
        *args: SetDefaultsT,
        all: SetDefaultsValueT | None = None,
        extend: bool = False,
        ignore_unknown_fields: bool = False,
        ignore_unknown_targets: bool = False,
    ) -> None:
        builders: dict[str, TargetDefaults.Builder] = (
            {} if not extend else self._create_target_defaults_builders()
        )

        if all is not None:
            self._process_defaults(
                builders,
                {tuple(self.registered_target_types.aliases): all},
                ignore_unknown_fields=True,
                ignore_unknown_targets=ignore_unknown_targets,
            )

        for arg in args:
            self._process_defaults(
                builders,
                arg,
                ignore_unknown_fields=ignore_unknown_fields,
                ignore_unknown_targets=ignore_unknown_targets,
            )

        # Update with new defaults, dropping targets without any default values.
        for tgt, builder in builders.items():
            if not builder:
                self.defaults.pop(tgt, None)
            else:
                self.defaults[tgt] = builder.to_defaults(self.address)

    def _create_target_defaults_builders(self) -> dict[str, TargetDefaults.Builder]:
        return {
            k: TargetDefaults.Builder.from_defaults(
                v,
                self.registered_target_types.aliases_to_types[k],
                self.union_membership,
            )
            for k, v in self.defaults.items()
        }

    def _process_defaults(
        self,
        builders: dict[str, TargetDefaults.Builder],
        targets_defaults: SetDefaultsT,
        ignore_unknown_fields: bool = False,
        ignore_unknown_targets: bool = False,
    ):
        if not isinstance(targets_defaults, dict):
            raise ValueError(
                f"Expected dictionary mapping targets to default field values for {self.address} "
                f"but got: {type(targets_defaults).__name__}."
            )

        types = self.registered_target_types.aliases_to_types
        for target, defaults in targets_defaults.items():
            if not isinstance(defaults, (dict, list, tuple)):
                raise ValueError(
                    f"Invalid default field values in {self.address} for target type {target}, "
                    f"must be an `dict` or `list` but was {defaults!r} with type `{type(defaults).__name__}`."
                )

            targets: Iterable[str]
            targets = target if isinstance(target, tuple) else (target,)
            for target_alias in map(str, targets):
                if target_alias in types:
                    target_type = types[target_alias]
                elif ignore_unknown_targets:
                    continue
                else:
                    raise ValueError(f"Unrecognized target type {target_alias} in {self.address}.")

                builder = builders.get(target_type.alias)
                if builder is None:
                    builder = TargetDefaults.Builder(
                        target_type=target_type, union_membership=self.union_membership
                    )
                    builders[target_type.alias] = builder

                if isinstance(defaults, dict):
                    builder.update_field_defaults(defaults, ignore_unknown_fields)
                else:
                    builder.update_args_defaults(defaults)
