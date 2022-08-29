# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.util.value_interpolation import InterpolationError, InterpolationValue


class HelmEnvironmentInterpolationError(InterpolationError):
    @classmethod
    def attribute_error(
        cls, value: str | InterpolationValue, attribute: str
    ) -> HelmEnvironmentInterpolationError:
        msg = f"The environment variable {attribute!r} is undefined."
        if value and isinstance(value, HelmEnvironmentInterpolationValue):
            msg += f' Available environment variables are: {", ".join(value.keys())}.'
        msg += "\n\nAvailable environment variables are defined using the `[helm].extra_env_vars` option."
        return cls(msg)


class HelmEnvironmentInterpolationValue(InterpolationValue):
    """Interpolation context value with specific error handling for environment variables."""

    _attribute_error_type = HelmEnvironmentInterpolationError
