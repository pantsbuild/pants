# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass
from typing import Any, Iterator, cast

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
from pants.util.strutil import bullet_list, softwrap


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

    args: tuple[str, ...]
    kwargs: FrozenDict[str, ImmutableValue]

    def __init__(self, *args: str, **kwargs: Any) -> None:
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "kwargs", FrozenDict.deep_freeze(kwargs))

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

    @classmethod
    def expand(
        cls, address: Address, fields: dict[str, Any | Parametrize]
    ) -> Iterator[tuple[Address, dict[str, Any]]]:
        """Produces the cartesian product of fields for the given possibly-Parametrized fields.

        Only one level of expansion is performed: if individual field values might also contain
        Parametrize instances (in particular: an `overrides` field), expanding those will require
        separate calls.
        """
        try:
            parametrized: list[list[tuple[str, str, Any]]] = [
                [
                    (field_name, alias, field_value)
                    for alias, field_value in v.to_parameters().items()
                ]
                for field_name, v in fields.items()
                if isinstance(v, Parametrize)
            ]
        except Exception as e:
            raise Exception(f"Failed to parametrize `{address}`:\n{e}") from e

        if not parametrized:
            yield (address, fields)
            return

        non_parametrized = tuple(
            (field_name, field_value)
            for field_name, field_value in fields.items()
            if not isinstance(field_value, Parametrize)
        )

        for parametrized_args in itertools.product(*parametrized):
            expanded_address = address.parametrize(
                {field_name: alias for field_name, alias, _ in parametrized_args}
            )
            parametrized_args_fields = tuple(
                (field_name, field_value) for field_name, _, field_value in parametrized_args
            )
            expanded_fields: dict[str, Any] = dict(non_parametrized + parametrized_args_fields)
            yield expanded_address, expanded_fields

    def __repr__(self) -> str:
        strs = [str(s) for s in self.args]
        strs.extend(f"{alias}={value}" for alias, value in self.kwargs.items())
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

            # Else, see whether any of the generated targets match.
            for candidate in parametrization.parametrization.values():
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
