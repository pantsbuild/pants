# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.util.value_interpolation import InterpolationError, InterpolationValue


class DockerBuildArgsInterpolationError(InterpolationError):
    @classmethod
    def attribute_error(
        cls, value: str | InterpolationValue, attribute: str
    ) -> DockerBuildArgsInterpolationError:
        msg = f"The build arg {attribute!r} is undefined."
        if value and isinstance(value, DockerBuildArgsInterpolationValue):
            msg += f' Defined build args are: {", ".join(value.keys())}.'
        msg += (
            "\n\nThis build arg may be defined with the `[docker].build_args` option or directly "
            "on the `docker_image` target using the `extra_build_args` field."
        )
        return cls(msg)


class DockerBuildArgsInterpolationValue(InterpolationValue):
    """Interpolation context value with specific error handling for build args."""

    _attribute_error_type = DockerBuildArgsInterpolationError
