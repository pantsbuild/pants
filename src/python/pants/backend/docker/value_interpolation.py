# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar, Mapping

from pants.util.frozendict import FrozenDict


class DockerInterpolationError(ValueError):
    @classmethod
    def attribute_error(
        cls, value: DockerInterpolationValue, attribute: str
    ) -> DockerInterpolationError:
        msg = f"The placeholder {attribute!r} is unknown."
        if value:
            msg += f' Try with one of: {", ".join(value.keys())}.'
        return cls(msg)


class DockerInterpolationValue(FrozenDict[str, str]):
    """Dict class suitable for use as a format string context object, as it allows to use attribute
    access rather than item access."""

    _attribute_error_type: ClassVar[type[DockerInterpolationError]] = DockerInterpolationError

    @classmethod
    def create(
        cls, value: Mapping[str, str] | DockerInterpolationValue
    ) -> DockerInterpolationValue:
        """Create new instance of `DockerInterpolationValue` unless `value` already is an instance
        (or subclass) of `DockerInterpolationValue`, in which case `value` is returned as-is."""
        if isinstance(value, cls):
            return value
        return cls(value)

    def __getattr__(self, attribute: str) -> str:
        if attribute not in self:
            raise self._attribute_error_type.attribute_error(self, attribute)
        return self[attribute]


class DockerBuildArgInterpolationError(DockerInterpolationError):
    @classmethod
    def attribute_error(
        cls, value: DockerInterpolationValue, attribute: str
    ) -> DockerInterpolationError:
        msg = f"The build arg {attribute!r} is undefined."
        if value:
            msg += f' Defined build args are: {", ".join(value.keys())}.'
        msg += (
            "\n\nThis build arg may be defined with the `[docker].build_args` option or directly "
            "on the `docker_image` target using the `extra_build_args` field."
        )
        return cls(msg)


class DockerBuildArgsInterpolationValue(DockerInterpolationValue):
    """Interpolation context value with specific error handling for build args."""

    _attribute_error_type = DockerBuildArgInterpolationError


class DockerInterpolationContext(FrozenDict[str, DockerInterpolationValue]):
    @classmethod
    def from_dict(
        cls, data: Mapping[str, Mapping[str, str] | DockerInterpolationValue]
    ) -> DockerInterpolationContext:
        return DockerInterpolationContext(
            {key: DockerInterpolationValue.create(value) for key, value in data.items()}
        )

    def merge(self, other: Mapping[str, Mapping[str, str]]) -> DockerInterpolationContext:
        return DockerInterpolationContext.from_dict({**self, **other})
