# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Mapping, TypeVar, Union

from pants.engine.addresses import Address
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


class InterpolationError(ValueError):
    @classmethod
    def attribute_error(cls, value: str | InterpolationValue, attribute: str) -> InterpolationError:
        msg = f"The placeholder {attribute!r} is unknown."
        if value and isinstance(value, InterpolationValue):
            msg += f' Try with one of: {", ".join(value.keys())}.'
        return cls(msg)


ErrorT = TypeVar("ErrorT", bound=InterpolationError)


class InterpolationValue(FrozenDict[str, str]):
    """Dict class suitable for use as a format string context object, as it allows to use attribute
    access rather than item access."""

    _attribute_error_type: ClassVar[type[InterpolationError]] = InterpolationError

    def __getattr__(self, attribute: str) -> str:
        if attribute not in self:
            raise self._attribute_error_type.attribute_error(self, attribute)
        return self[attribute]


class InterpolationContext(FrozenDict[str, Union[str, InterpolationValue]]):
    @classmethod
    def from_dict(cls, data: Mapping[str, str | Mapping[str, str]]) -> InterpolationContext:
        return InterpolationContext({key: cls.create_value(value) for key, value in data.items()})

    @staticmethod
    def create_value(value: str | Mapping[str, str]) -> str | InterpolationValue:
        """Ensure that `value` satisfies the type `InterpolationValue`."""
        if isinstance(value, (str, InterpolationValue)):
            return value
        return InterpolationValue(value)

    def merge(self, other: Mapping[str, str | Mapping[str, str]]) -> InterpolationContext:
        return InterpolationContext.from_dict({**self, **other})

    def format(
        self, text: str, *, source: TextSource, error_cls: type[ErrorT] | None = None
    ) -> str:
        stack = [text]
        try:
            while "{" in stack[-1] and "}" in stack[-1]:
                if len(stack) >= 5:
                    raise InterpolationError(
                        "The formatted placeholders recurse too deep.\n"
                        + " => ".join(map(repr, stack))
                    )
                stack.append(stack[-1].format(**self))
                if stack[-1] == stack[-2]:
                    break
            return stack[-1]
        except (KeyError, InterpolationError) as e:
            default_error_cls = InterpolationError
            msg = f"Invalid value for the {source}: {text!r}.\n\n"
            if isinstance(e, InterpolationError):
                default_error_cls = type(e)
                msg += str(e)
            else:
                # KeyError
                msg += f"The placeholder {e} is unknown."
                if self:
                    msg += f" Try with one of: {', '.join(sorted(self.keys()))}."
                else:
                    msg += " "
                    msg += softwrap(
                        f"""
                        There are currently no known placeholders to use.

                        Check the documentation of the {source} to understand where you may need
                        to configure your placeholders.
                        """
                    )
            raise (error_cls or default_error_cls)(msg) from e

    @dataclass(frozen=True)
    class TextSource:
        address: Address | None = None
        target_alias: str | None = None
        field_alias: str | None = None
        options_scope: str | None = None

        def __post_init__(self):
            field_infos_is_none = (
                x is None for x in [self.address, self.target_alias, self.field_alias]
            )
            if self.options_scope is None:
                assert not any(field_infos_is_none), f"Missing target field details in {self!r}."
            else:
                assert all(
                    field_infos_is_none
                ), f"Must not refer to both configuration option and target field in {self!r}."

        def __str__(self) -> str:
            if self.options_scope:
                return f"`{self.options_scope}` configuration option"
            return (
                f"`{self.field_alias}` field of the `{self.target_alias}` target at {self.address}"
            )
