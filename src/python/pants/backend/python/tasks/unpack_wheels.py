# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from hashlib import sha1

from pex.pex_builder import PEXBuilder

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.unpacked_whls import UnpackedWheels
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_setup import PythonSetup
from pants.task.unpack_remote_sources_base import UnpackRemoteSourcesBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import mergetree, safe_concurrent_creation
from pants.util.memo import memoized_method
from pants.util.objects import SubclassesOf


class UnpackWheelsFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):
    def compute_fingerprint(self, target):
        """UnpackedWheels targets need to be re-unpacked if any of its configuration changes or any
        of the jars they import have changed."""
        if isinstance(target, UnpackedWheels):
            hasher = sha1()
            for cache_key in sorted(req.cache_key() for req in target.all_imported_requirements):
                hasher.update(cache_key.encode())
            hasher.update(target.payload.fingerprint().encode())
            return hasher.hexdigest()
        return None


class UnpackWheels(UnpackRemoteSourcesBase):
    """Extract native code from `NativePythonWheel` targets for use by downstream C/C++ sources."""

    source_target_constraint = SubclassesOf(UnpackedWheels)

    def get_fingerprint_strategy(self):
        return UnpackWheelsFingerprintStrategy()

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            PexBuilderWrapper.Factory,
            PythonInterpreterCache,
            PythonSetup,
        )

    class SingleDistExtractionError(Exception):
        pass

    def _get_matching_wheel(self, pex_path, interpreter, requirements, module_name):
        """Use PexBuilderWrapper to resolve a single wheel from the requirement specs using pex.

        N.B.: The resolved wheel is already "unpacked" by PEX. More accurately, it's installed in a
        chroot.
        """
        with self.context.new_workunit("extract-native-wheels"):
            with safe_concurrent_creation(pex_path) as chroot:
                pex_builder = PexBuilderWrapper.Factory.create(
                    builder=PEXBuilder(path=chroot, interpreter=interpreter), log=self.context.log
                )

                resolved_dists = pex_builder.resolve_distributions(
                    requirements, platforms=["current"]
                )

                matched_dists = [
                    resolved_dist.distribution
                    for resolved_dist in resolved_dists
                    if resolved_dist.distribution.key == module_name
                ]
                if len(matched_dists) != 1:
                    raise self.SingleDistExtractionError(
                        f"Exactly one dist was expected to match name {module_name} in requirements "
                        f"{requirements}, found {matched_dists}"
                    )
                return matched_dists[0]

    @memoized_method
    def _compatible_interpreter(self, unpacked_whls):
        constraints = PythonSetup.global_instance().compatibility_or_constraints(
            unpacked_whls.compatibility
        )
        allowable_interpreters = PythonInterpreterCache.global_instance().setup(filters=constraints)
        return min(allowable_interpreters)

    class WheelUnpackingError(TaskError):
        pass

    def unpack_target(self, unpacked_whls, unpack_dir):
        interpreter = self._compatible_interpreter(unpacked_whls)

        with temporary_dir() as resolve_dir:
            try:
                matched_dist = self._get_matching_wheel(
                    resolve_dir,
                    interpreter,
                    unpacked_whls.all_imported_requirements,
                    unpacked_whls.module_name,
                )
                wheel_chroot = matched_dist.location
                if unpacked_whls.within_data_subdir:
                    # N.B.: Wheels with data dirs have the data installed under the top module.
                    dist_data_dir = os.path.join(wheel_chroot, unpacked_whls.module_name)
                else:
                    dist_data_dir = wheel_chroot

                unpack_filter = self.get_unpack_filter(unpacked_whls)
                # Copy over the module's data files into `unpack_dir`.
                mergetree(dist_data_dir, unpack_dir, file_filter=unpack_filter)
            except Exception as e:
                raise self.WheelUnpackingError(
                    "Error extracting wheel for target {}: {}".format(unpacked_whls, str(e)), e
                )
