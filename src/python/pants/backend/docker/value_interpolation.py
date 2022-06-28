# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Mapping, TypeVar, Union

from pants.engine.addresses import Address
from pants.util.frozendict import FrozenDict


class DockerInterpolationError(ValueError):
    @classmethod
    def attribute_error(
        cls, value: str | DockerInterpolationValue, attribute: str
    ) -> DockerInterpolationError:
        msg = f"The placeholder {attribute!r} is unknown."
        if value and isinstance(value, DockerInterpolationValue):
            msg += f' Try with one of: {", ".join(value.keys())}.'
        return cls(msg)


ErrorT = TypeVar("ErrorT", bound=DockerInterpolationError)


class DockerInterpolationValue(FrozenDict[str, str]):
    """Dict class suitable for use as a format string context object, as it allows to use attribute
    access rather than item access."""

    _attribute_error_type: ClassVar[type[DockerInterpolationError]] = DockerInterpolationError

    def __getattr__(self, attribute: str) -> str:
        if attribute not in self:
            raise self._attribute_error_type.attribute_error(self, attribute)
        return self[attribute]


class DockerBuildArgInterpolationError(DockerInterpolationError):
    @classmethod
    def attribute_error(
        cls, value: str | DockerInterpolationValue, attribute: str
    ) -> DockerInterpolationError:
        msg = f"The build arg {attribute!r} is undefined."
        if value and isinstance(value, DockerInterpolationValue):
            msg += f' Defined build args are: {", ".join(value.keys())}.'
        msg += (
            "\n\nThis build arg may be defined with the `[docker].build_args` option or directly "
            "on the `docker_image` target using the `extra_build_args` field."
        )
        return cls(msg)


class DockerBuildArgsInterpolationValue(DockerInterpolationValue):
    """Interpolation context value with specific error handling for build args."""

    _attribute_error_type = DockerBuildArgInterpolationError


class DockerInterpolationContext(FrozenDict[str, Union[str, DockerInterpolationValue]]):
    @classmethod
    def from_dict(cls, data: Mapping[str, str | Mapping[str, str]]) -> DockerInterpolationContext:
        return DockerInterpolationContext(
            {key: cls.create_value(value) for key, value in data.items()}
        )

    @staticmethod
    def create_value(value: str | Mapping[str, str]) -> str | DockerInterpolationValue:
        """Ensure that `value` satisfies the type `DockerInterpolationValue`."""
        if isinstance(value, (str, DockerInterpolationValue)):
            return value
        return DockerInterpolationValue(value)

    def merge(self, other: Mapping[str, str | Mapping[str, str]]) -> DockerInterpolationContext:
        return DockerInterpolationContext.from_dict({**self, **other})

    def format(
        self, text: str, *, source: TextSource, error_cls: type[ErrorT] | None = None
    ) -> str:
        stack = [text]
        try:
            while "{" in stack[-1] and "}" in stack[-1]:
                if len(stack) >= 5:
                    raise DockerInterpolationError(
                        "The formatted placeholders recurse too deep.\n"
                        + " => ".join(map(repr, stack))
                    )
                stack.append(stack[-1].format(**self))
                if stack[-1] == stack[-2]:
                    break
            return stack[-1]
        except (KeyError, DockerInterpolationError) as e:
            default_error_cls = DockerInterpolationError
            msg = f"Invalid value for the {source}: {text!r}.\n\n"
            if isinstance(e, DockerInterpolationError):
                default_error_cls = type(e)
                msg += str(e)
            else:
                # KeyError
                msg += f"The placeholder {e} is unknown."
                if self:
                    msg += f" Try with one of: {', '.join(sorted(self.keys()))}."
                else:
                    msg += (
                        " There are currently no known placeholders to use. These placeholders "
                        "can come from `[docker].build_args` or parsed from instructions in your "
                        "`Dockerfile`."
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
