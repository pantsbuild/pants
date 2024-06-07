# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import operator
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Any, Iterator, Mapping, cast

from typing_extensions import Self

from pants.build_graph.address import BANNED_CHARS_IN_PARAMETERS
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.target import (
    Field,
    FieldDefaults,
    ImmutableValue,
    Target,
    TargetTypesToGenerateTargetsRequests,
)
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list, pluralize, softwrap


def _named_args_explanation(arg: str) -> str:
    return (
        f"To use `{arg}` as a parameter, you can pass it as a keyword argument to "
        f"give it an alias. For example: `parametrize(short_memorable_name={arg})`"
    )


@dataclass(frozen=True)
class Parametrize:
    """A builtin function/dataclass that can be used to parametrize Targets.

    Parametrization is applied between TargetAdaptor construction and Target instantiation, which
    means that individual Field instances need not be aware of it.
    """

    class _MergeBehaviour(Enum):
        # Do not merge this parametrization.
        never = "never"
        # Discard this parametrization with `other`.
        replace = "replace"

    args: tuple[str, ...]
    kwargs: FrozenDict[str, ImmutableValue]
    is_group: bool
    merge_behaviour: _MergeBehaviour = dataclasses.field(compare=False)

    def __init__(self, *args: str, **kwargs: Any) -> None:
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "kwargs", FrozenDict.deep_freeze(kwargs))
        object.__setattr__(self, "is_group", False)
        object.__setattr__(self, "merge_behaviour", Parametrize._MergeBehaviour.never)

    def keys(self) -> tuple[str]:
        return (f"parametrize_{hash(self.args)}:{id(self)}",)

    def __getitem__(self, key) -> Any:
        if isinstance(key, str) and key.startswith("parametrize_"):
            return self.to_group()
        else:
            raise KeyError(key)

    def to_group(self) -> Self:
        object.__setattr__(self, "is_group", True)
        return self

    def to_weak(self) -> Self:
        object.__setattr__(self, "merge_behaviour", Parametrize._MergeBehaviour.replace)
        return self

    def to_parameters(self) -> dict[str, Any]:
        """Validates and returns a mapping from aliases to parameter values.

        This conversion is executed lazily to allow for more context in error messages, such as the
        TargetAdaptor consuming the Parametrize instance.
        """
        parameters = dict(self.kwargs)
        for arg in self.args:
            if not isinstance(arg, str):
                raise Exception(
                    f"In {self}:\n  Positional arguments must be strings, but "
                    f"`{arg!r}` was a `{type(arg).__name__}`.\n\n"
                    + _named_args_explanation(f"{arg!r}")
                )
            previous_arg = parameters.get(arg)
            if previous_arg is not None:
                raise Exception(
                    f"In {self}:\n  Positional arguments cannot have the same name as "
                    f"keyword arguments. `{arg}` was also defined as `{arg}={previous_arg!r}`."
                )
            banned_chars = BANNED_CHARS_IN_PARAMETERS & set(arg)
            if banned_chars:
                raise Exception(
                    f"In {self}:\n  Positional argument `{arg}` contained separator characters "
                    f"(`{'`,`'.join(banned_chars)}`).\n\n" + _named_args_explanation(arg)
                )
            parameters[arg] = arg
        return parameters

    @property
    def group_name(self) -> str:
        assert self.is_group
        if len(self.args) == 1:
            name = self.args[0]
            banned_chars = BANNED_CHARS_IN_PARAMETERS & set(name)
            if banned_chars:
                raise Exception(
                    f"In {self}:\n  Parametrization group name `{name}` contained separator characters "
                    f"(`{'`,`'.join(banned_chars)}`)."
                )
            return name
        else:
            raise ValueError(
                softwrap(
                    f"""
                    A parametrize group must begin with the group name followed by the target field
                    values for the group.

                    Example:

                        target(
                            ...,
                            **parametrize("group-a", field_a=1, field_b=True),
                        )

                    Got: `{self!r}`
                    """
                )
            )

    @classmethod
    def expand(
        cls, address: Address, fields: Mapping[str, Any | Parametrize]
    ) -> Iterator[tuple[Address, Mapping[str, Any]]]:
        """Produces the cartesian product of fields for the given possibly-Parametrized fields.

        Only one level of expansion is performed: if individual field values might also contain
        Parametrize instances (in particular: an `overrides` field), expanding those will require
        separate calls.

        Parametrized groups are expanded however (that is: any `parametrize` field values in a
        `**parametrize()` group are also expanded).
        """
        try:
            parametrizations = cls._collect_parametrizations(fields)
            cls._check_parametrizations(parametrizations)
            parametrized: list[list[tuple[str, str, Any]]] = [
                [
                    (field_name, alias, field_value)
                    for alias, field_value in v.to_parameters().items()
                ]
                for field_name, v in parametrizations.get(None, ())
            ]
            parametrized_groups: list[tuple[str, str, Parametrize]] = [
                ("parametrize", group_name, vs[0][1])
                for group_name, vs in parametrizations.items()
                if group_name is not None
            ]
        except Exception as e:
            raise Exception(f"Failed to parametrize `{address}`:\n  {e}") from e

        parameters = address.parameters
        non_parametrized = tuple(
            (field_name, field_value)
            for field_name, field_value in fields.items()
            if not isinstance(field_value, Parametrize)
        )
        if parametrized_groups:
            # Add the groups as one vector for the cross-product.
            parametrized.append(parametrized_groups)

        unparametrize_keys = {k for k, _ in non_parametrized if k in parameters}

        # Remove non-parametrized fields from the address parameters.
        for k in unparametrize_keys:
            parameters.pop(k, None)

        if not parametrized:
            if unparametrize_keys:
                address = address.parametrize(parameters, replace=True)
            yield (address, fields)
            return

        for parametrized_args in itertools.product(*parametrized):
            expanded_parameters = parameters | {
                field_name: alias for field_name, alias, _ in parametrized_args
            }
            # There will be at most one group per cross product.
            group_kwargs: Mapping[str, Any] = next(
                (
                    field_value.kwargs
                    for _, _, field_value in parametrized_args
                    if isinstance(field_value, Parametrize) and field_value.is_group
                ),
                {},
            )
            # Exclude fields from parametrize group from address parameters.
            for k in group_kwargs.keys() & parameters.keys():
                expanded_parameters.pop(k, None)

            parametrized_args_fields = tuple(
                (field_name, field_value)
                for field_name, _, field_value in parametrized_args
                # Exclude any parametrize group
                if not (isinstance(field_value, Parametrize) and field_value.is_group)
            )
            expanded_fields: dict[str, Any] = dict(non_parametrized + parametrized_args_fields)
            expanded_address = address.parametrize(expanded_parameters, replace=True)

            if any(isinstance(group_value, Parametrize) for group_value in group_kwargs.values()):
                # Expand nested parametrize within a parametrized group.
                for grouped_address, grouped_fields in Parametrize.expand(
                    expanded_address, group_kwargs
                ):
                    yield expanded_address.parametrize(
                        grouped_address.parameters
                    ), expanded_fields | grouped_fields
            else:
                yield expanded_address, expanded_fields | group_kwargs

    @staticmethod
    def _collect_parametrizations(
        fields: Mapping[str, Any | Parametrize]
    ) -> Mapping[str | None, list[tuple[str, Parametrize]]]:
        parametrizations = defaultdict(list)
        for field_name, v in fields.items():
            if not isinstance(v, Parametrize):
                continue
            group_name = None if not v.is_group else v.group_name
            parametrizations[group_name].append((field_name, v))
        return parametrizations

    @staticmethod
    def _check_parametrizations(
        parametrizations: Mapping[str | None, list[tuple[str, Parametrize]]]
    ) -> None:
        for group_name, groups in parametrizations.items():
            if group_name is not None and len(groups) > 1:
                group = Parametrize._combine(*(group for _, group in groups))
                groups.clear()
                groups.append(("combined", group))

        parametrize_field_names = {field_name for field_name, v in parametrizations.get(None, ())}
        parametrize_field_names_from_groups = {
            field_name
            for group_name, groups in parametrizations.items()
            if group_name is not None
            for field_name in groups[0][1].kwargs.keys()
        }
        conflicting = parametrize_field_names.intersection(parametrize_field_names_from_groups)
        if conflicting:
            raise ValueError(
                softwrap(
                    f"""
                    Conflicting parametrizations for {pluralize(len(conflicting), "field", include_count=False)}:
                    {', '.join(sorted(conflicting))}
                    """
                )
            )

    @staticmethod
    def _combine(head: Parametrize, *tail: Parametrize) -> Parametrize:
        return reduce(operator.add, tail, head)

    def __add__(self, other: Parametrize) -> Parametrize:
        if not isinstance(other, Parametrize):
            raise TypeError(f"Can not combine {self} with {other!r}")
        if self.merge_behaviour is Parametrize._MergeBehaviour.replace:
            return other
        if other.merge_behaviour is Parametrize._MergeBehaviour.replace:
            return self
        if self.is_group and other.is_group:
            raise ValueError(f"Parametrization group name is not unique: {self.group_name!r}")
        raise ValueError(f"Can not combine parametrizations: {self} | {other}")

    def __repr__(self) -> str:
        strs = [repr(s) for s in self.args]
        strs.extend(f"{alias}={value!r}" for alias, value in self.kwargs.items())
        return f"parametrize({', '.join(strs)})"


@dataclass(frozen=True)
class _TargetParametrization:
    original_target: Target | None
    parametrization: FrozenDict[Address, Target]

    @property
    def all(self) -> Iterator[Target]:
        if self.original_target:
            yield self.original_target
        yield from self.parametrization.values()

    def get(self, address: Address) -> Target | None:
        """Find the Target with an exact Address match, if any."""
        if self.original_target and self.original_target.address == address:
            return self.original_target
        return self.parametrization.get(address)


# TODO: This is not the right name for this class, nor the best place for it to live. But it is
# consumed by both `pants.engine.internals.graph` and `pants.engine.internals.build_files`, and
# shouldn't live in `pants.engine.target` (yet? needs more stabilization).
@dataclass(frozen=True)
class _TargetParametrizationsRequest(EngineAwareParameter):
    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    def __post_init__(self) -> None:
        if self.address.is_parametrized or self.address.is_generated_target:
            raise ValueError(
                softwrap(
                    f"""
                    Cannot create {self.__class__.__name__} on a generated or parametrized target.

                    Self: {self}
                    """
                )
            )

    def debug_hint(self) -> str:
        return self.address.spec


# TODO: See TODO on _TargetParametrizationsRequest about naming this.
class _TargetParametrizations(Collection[_TargetParametrization]):
    """All parametrizations and generated targets for a single input Address.

    If a Target has been parametrized, the original Target might _not_ be present, due to no Target
    being addressable at the un-parameterized Address.
    """

    @property
    def all(self) -> Iterator[Target]:
        """Iterates over all Target instances which are valid after parametrization."""
        for parametrization in self:
            yield from parametrization.all

    @property
    def parametrizations(self) -> dict[Address, Target]:
        """Returns a merged dict of all generated/parametrized instances, excluding originals."""
        return {
            a: t for parametrization in self for a, t in parametrization.parametrization.items()
        }

    def generated_for(self, address: Address) -> FrozenDict[Address, Target]:
        """Find all Targets generated by the given generator Address."""
        assert not address.is_generated_target
        for parametrization in self:
            if (
                parametrization.original_target
                and parametrization.original_target.address == address
            ):
                return parametrization.parametrization

        raise self._bare_address_error(address)

    def get(
        self,
        address: Address,
        target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests | None = None,
    ) -> Target | None:
        """Find the Target with an exact Address match, if any."""
        for parametrization in self:
            instance = parametrization.get(address)
            if instance is not None:
                return instance

        # TODO: This is an accommodation to allow using file/generator Addresses for
        # non-generator atom targets. See https://github.com/pantsbuild/pants/issues/14419.
        if target_types_to_generate_requests and address.is_generated_target:
            base_address = address.maybe_convert_to_target_generator()
            original_target = self.get(base_address, target_types_to_generate_requests)
            if original_target and not target_types_to_generate_requests.is_generator(
                original_target
            ):
                return original_target

        return None

    def get_all_superset_targets(self, address: Address) -> Iterator[Address]:
        """Yield the input address itself, or any parameterized addresses which are a superset of
        the input address.

        For example, an input address `dir:tgt` may yield `(dir:tgt@k=v1, dir:tgt@k=v2)`.

        If no targets are a match, will yield nothing.
        """
        # Check for exact matches.
        if self.get(address) is not None:
            yield address
            return

        for parametrization in self:
            if parametrization.original_target is not None and address.is_parametrized_subset_of(
                parametrization.original_target.address
            ):
                yield parametrization.original_target.address

            for parametrized_tgt in parametrization.parametrization.values():
                if address.is_parametrized_subset_of(parametrized_tgt.address):
                    yield parametrized_tgt.address

    def get_subset(
        self,
        address: Address,
        consumer: Target,
        field_defaults: FieldDefaults,
        target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    ) -> Target:
        """Find the Target with the given Address, or with fields matching the given consumer."""
        # Check for exact matches.
        instance = self.get(address, target_types_to_generate_requests)
        if instance is not None:
            return instance

        def remaining_fields_match(candidate: Target) -> bool:
            """Returns true if all Fields absent from the candidate's Address match the consumer."""
            unspecified_param_field_names = {
                key for key in candidate.address.parameters.keys() if key not in address.parameters
            }
            return all(
                _concrete_fields_are_equivalent(
                    field_defaults,
                    consumer=consumer,
                    candidate_field=field,
                )
                for field_type, field in candidate.field_values.items()
                if field_type.alias in unspecified_param_field_names
            )

        for parametrization in self:
            # If the given Address is a subset-match of the parametrization's original Target
            # (meaning that the user specified an un-parameterized generator Address), then we
            # need to match against one of the generated Targets instead (because a parametrized
            # generator does not keep its Fields).
            if (
                parametrization.original_target
                and address.is_parametrized_subset_of(parametrization.original_target.address)
                and parametrization.parametrization
                and remaining_fields_match(next(iter(parametrization.parametrization.values())))
            ):
                return parametrization.original_target

        consumer_parametrize_group = consumer.address.parameters.get("parametrize")

        def matching_parametrize_group(candidate: Target) -> bool:
            return candidate.address.parameters.get("parametrize") == consumer_parametrize_group

        for candidate in sorted(
            self.parametrizations.values(), key=matching_parametrize_group, reverse=True
        ):
            # Else, see whether any of the generated targets match, preferring a matching
            # parametrize group when available.
            if address.is_parametrized_subset_of(candidate.address) and remaining_fields_match(
                candidate
            ):
                return candidate

        raise ValueError(
            f"The explicit dependency `{address}` of the target at `{consumer.address}` does "
            "not provide enough address parameters to identify which parametrization of the "
            "dependency target should be used.\n"
            f"Target `{address.maybe_convert_to_target_generator()}` can be addressed as:\n"
            f"{bullet_list(str(t.address) for t in self.all)}"
        )

    def generated_or_generator(self, maybe_generator: Address) -> Iterator[Target]:
        """Yield either the Target, or the generated Targets for the given Address."""
        for parametrization in self:
            if (
                not parametrization.original_target
                or parametrization.original_target.address != maybe_generator
            ):
                continue
            if parametrization.parametrization:
                # Generated Targets.
                yield from parametrization.parametrization.values()
            else:
                # Did not generate targets.
                yield parametrization.original_target
            return

        raise self._bare_address_error(maybe_generator)

    def _bare_address_error(self, address) -> ValueError:
        return ValueError(
            "A `parametrized` target cannot be consumed without its parameters specified.\n"
            f"Target `{address}` can be addressed as:\n"
            f"{bullet_list(str(t.address) for t in self.all)}"
        )


def _concrete_fields_are_equivalent(
    field_defaults: FieldDefaults, *, consumer: Target, candidate_field: Field
) -> bool:
    candidate_field_type = type(candidate_field)
    candidate_field_value = field_defaults.value_or_default(candidate_field)

    if consumer.has_field(candidate_field_type):
        return cast(
            bool,
            field_defaults.value_or_default(consumer[candidate_field_type])
            == candidate_field_value,
        )
    # Else, see if the consumer has a field that is a superclass of `candidate_field_value`, to
    # handle https://github.com/pantsbuild/pants/issues/16190. This is only safe because we are
    # confident that both `candidate_field_type` and the fields from `consumer` are _concrete_,
    # meaning they are not abstract templates like `StringField`.
    superclass = next(
        (
            consumer_field
            for consumer_field in consumer.field_types
            if isinstance(candidate_field, consumer_field)
        ),
        None,
    )
    if superclass is None:
        return False
    return cast(
        bool, field_defaults.value_or_default(consumer[superclass]) == candidate_field_value
    )
