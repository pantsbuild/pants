# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Mapping, Sequence

from pants.base.deprecated import warn_or_error
from pants.engine.env_vars import EnvironmentVars
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PythonNativeCodeSubsystem(Subsystem):
    options_scope = "python-native-code"
    help = "Options for building native code using Python, e.g. when resolving distributions."

    class EnvironmentAware(Subsystem.EnvironmentAware):
        # TODO(#7735): move the --cpp-flags and --ld-flags to a general subprocess support subsystem.
        _cpp_flags = StrListOption(
            default=["<CPPFLAGS>"],
            help=(
                "Override the `CPPFLAGS` environment variable for any forked subprocesses. "
                "Use the value `['<CPPFLAGS>']` to inherit the value of the `CPPFLAGS` "
                "environment variable from your runtime environment target."
            ),
            advanced=True,
        )
        _ld_flags = StrListOption(
            default=["<LDFLAGS>"],
            help=(
                "Override the `LDFLAGS` environment variable for any forked subprocesses. "
                "Use the value `['<LDFLAGS>']` to inherit the value of the `LDFLAGS` environment "
                "variable from your runtime environment target."
            ),
            advanced=True,
        )

        @property
        def environment_dict(self) -> _MappingOrCallable:
            return _MappingOrCallable(self)

        @property
        def environment_dict_keys(self) -> tuple[str, ...]:
            return ("CPPFLAGS", "LDFLAGS")

        @property
        def cpp_flags(self) -> _SequenceOrCallable:
            return _SequenceOrCallable(self, "cpp_flags", self._cpp_flags, "CPPFLAGS")

        @property
        def ld_flags(self) -> _SequenceOrCallable:
            return _SequenceOrCallable(self, "ld_flags", self._ld_flags, "LDFLAGS")


@dataclass(frozen=True)
class _SequenceOrCallable(Sequence[str]):
    """Allow for access like a tuple or list (for deprecated use cases), or as a callable.

    This is to permit a deprecation cycle for
    `PythonNativeCodeSubsystem.EnvironmentAware.cpp_flags` and `.ld_flags`, which originally
    directly accessed the local environment variables (which breaks cache support), without
    getting in the way of existing static typing (unlike a `Union[...]` type declaration would
    cause).

    The class may be used as a sequence if the parent subsystem is for a `LocalEnvironmentTarget`,
    but will raise a deprecation warning. It will raise an error if used as a sequence for other
    environments.

    This class should be destroyed with extreme prejudice when the deprecation cycle is complete.
    It is awful.
    """

    subsystem: PythonNativeCodeSubsystem.EnvironmentAware
    property_name: str
    values: Sequence[str]
    env_var_name: str

    def __getitem__(self, *a, **k):
        return self._direct_access_env_var.__getitem__(*a, **k)

    @memoized_property
    def _direct_access_env_var(self) -> Sequence[str]:
        from pants.core.util_rules.environments import LocalEnvironmentTarget

        if not isinstance(self.subsystem.env_tgt.val, LocalEnvironmentTarget):
            removal_version = "2.15.0.dev0"
            addendum = " for a remote or docker runtime environment target"
        else:
            removal_version = "2.17.0.dev0"
            addendum = " "
        warn_or_error(
            removal_version,
            f"Using `PythonNativeCode.EnvironmentAware.{self.property_name}`{addendum} without "
            "passing in an `EnvironmentVars` object",
            f"Call `PythonNativeCode.EnvironmentAware.{self.property_name}(EnvironmentVars)` "
            "to get a value.",
        )

        return self._values(os.environ)

    def __len__(self) -> int:
        return len(self._direct_access_env_var)

    def __call__(self, env: EnvironmentVars) -> tuple[str, ...]:
        return self._values(env)

    def _values(self, env: Mapping[str, str]) -> tuple[str, ...]:
        def iter_values() -> Iterator[str]:
            for entry in self.values:
                if entry == f"<{self.env_var_name}>":
                    yield from safe_shlex_split(env.get(self.env_var_name, ""))
                else:
                    yield entry

        return tuple(iter_values())


@dataclass
class _MappingOrCallable(Mapping[str, str]):

    subsystem: PythonNativeCodeSubsystem.EnvironmentAware

    @memoized_property
    def _direct_access(self) -> Mapping[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.subsystem.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.subsystem.ld_flags),
        }

    def __getitem__(self, *a, **k):
        return self._direct_access.__getitem__(*a, **k)

    def __iter__(self) -> Iterator[str]:
        return iter(self._direct_access)

    def __len__(self) -> int:
        return len(self._direct_access)

    def __call__(self, env: EnvironmentVars) -> dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.subsystem.cpp_flags(env)),
            "LDFLAGS": safe_shlex_join(self.subsystem.ld_flags(env)),
        }
