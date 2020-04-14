# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict, Tuple

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.base.exceptions import IncompatiblePlatformsError
from pants.engine.rules import rule, subsystem_rule
from pants.python import pex_build_util
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf
from pants.util.strutil import safe_shlex_join, safe_shlex_split

logger = logging.getLogger(__name__)


class PythonNativeCode(Subsystem):
    """A subsystem which exposes components of the native backend to the python backend."""

    options_scope = "python-native-code"

    default_native_source_extensions = [".c", ".cpp", ".cc"]

    class PythonNativeCodeError(Exception):
        pass

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--native-source-extensions",
            type=list,
            default=cls.default_native_source_extensions,
            fingerprint=True,
            advanced=True,
            help="The extensions recognized for native source files in `python_dist()` sources.",
        )
        # TODO(#7735): move the --cpp-flags and --ld-flags to a general subprocess support subystem.
        register(
            "--cpp-flags",
            type=list,
            default=safe_shlex_split(os.environ.get("CPPFLAGS", "")),
            fingerprint=True,
            advanced=True,
            help="Override the `CPPFLAGS` environment variable for any forked subprocesses.",
        )
        register(
            "--ld-flags",
            type=list,
            default=safe_shlex_split(os.environ.get("LDFLAGS", "")),
            fingerprint=True,
            advanced=True,
            help="Override the `LDFLAGS` environment variable for any forked subprocesses.",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (NativeToolchain.scoped(cls), PythonSetup,)

    @memoized_property
    def _native_source_extensions(self):
        return self.get_options().native_source_extensions

    @memoized_property
    def native_toolchain(self):
        return NativeToolchain.scoped_instance(self)

    @memoized_property
    def _python_setup(self):
        return PythonSetup.global_instance()

    def pydist_has_native_sources(self, target):
        return target.has_sources(extension=tuple(self._native_source_extensions))

    @memoized_property
    def _native_target_matchers(self):
        return {
            SubclassesOf(PythonDistribution): self.pydist_has_native_sources,
            SubclassesOf(NativeLibrary): NativeLibrary.produces_ctypes_native_library,
        }

    def _any_targets_have_native_sources(self, targets):
        # TODO(#5949): convert this to checking if the closure of python requirements has any
        # platform-specific packages (maybe find the platforms there too?).
        for tgt in targets:
            for type_constraint, target_predicate in self._native_target_matchers.items():
                if type_constraint.satisfied_by(tgt) and target_predicate(tgt):
                    return True
        return False

    def check_build_for_current_platform_only(self, targets):
        """Performs a check of whether the current target closure has native sources and if so,
        ensures that Pants is only targeting the current platform.

        :param targets: a list of :class:`Target` objects.
        :return: a boolean value indicating whether the current target closure has native sources.
        :raises: :class:`pants.base.exceptions.IncompatiblePlatformsError`
        """
        # TODO(#5949): convert this to checking if the closure of python requirements has any
        # platform-specific packages (maybe find the platforms there too?).
        if not self._any_targets_have_native_sources(targets):
            return False

        platforms_with_sources = pex_build_util.targets_by_platform(targets, self._python_setup)
        platform_names = list(platforms_with_sources.keys())

        if not platform_names or platform_names == ["current"]:
            return True

        bad_targets = set()
        for platform, targets in platforms_with_sources.items():
            if platform == "current":
                continue
            bad_targets.update(targets)

        raise IncompatiblePlatformsError(
            dedent(
                """\
                Pants doesn't currently support cross-compiling native code.
                The following targets set platforms arguments other than ['current'], which is unsupported for this reason.
                Please either remove the platforms argument from these targets, or set them to exactly ['current'].
                Bad targets:
                {}
                """.format(
                    "\n".join(sorted(target.address.reference() for target in bad_targets))
                )
            )
        )


@dataclass(frozen=True)
class PexBuildEnvironment:
    cpp_flags: Tuple[str, ...]
    ld_flags: Tuple[str, ...]

    @property
    def invocation_environment_dict(self) -> Dict[str, str]:
        return {
            "CPPFLAGS": safe_shlex_join(self.cpp_flags),
            "LDFLAGS": safe_shlex_join(self.ld_flags),
        }


@rule
def create_pex_native_build_environment(
    python_native_code: PythonNativeCode,
) -> PexBuildEnvironment:
    return PexBuildEnvironment(
        cpp_flags=python_native_code.get_options().cpp_flags,
        ld_flags=python_native_code.get_options().ld_flags,
    )


def rules():
    return [
        subsystem_rule(PythonNativeCode),
        create_pex_native_build_environment,
    ]
