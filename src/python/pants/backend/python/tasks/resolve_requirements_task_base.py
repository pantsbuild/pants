# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.hash_utils import hash_all
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation
from pants.util.memo import memoized_property


class ResolveRequirementsTaskBase(Task):
    """Base class for tasks that resolve 3rd-party Python requirements.

    Creates an (unzipped) PEX on disk containing all the resolved requirements. This PEX can be
    merged with other PEXes to create a unified Python environment for running the relevant python
    code.
    """

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            PexBuilderWrapper.Factory,
            PythonSetup,
            PythonNativeCode.scoped(cls),
        )

    @memoized_property
    def _python_native_code_settings(self):
        return PythonNativeCode.scoped_instance(self)

    @memoized_property
    def _python_setup(self):
        return PythonSetup.global_instance()

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(PythonInterpreter)
        round_manager.optional_product(PythonRequirementLibrary)  # For local dists.
        # Codegen may inject extra resolvable deps, so make sure we have a product dependency
        # on relevant codegen tasks, if any.
        round_manager.optional_data("python")

    def resolve_requirements(self, interpreter, req_libs):
        """Requirements resolution for PEX files.

        NB: This method always resolve all requirements in `req_libs` for the 'current' platform! Tasks
        such as PythonBinaryCreate which export code meant for other machines to run will need to
        resolve against the platforms specified by the target or via pants options.

        :param interpreter: Resolve against this :class:`PythonInterpreter`.
        :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
        :returns: a PEX containing target requirements and any specified python dist targets.
        """
        with self.invalidated(req_libs) as invalidation_check:
            # If there are no relevant targets, we still go through the motions of resolving
            # an empty set of requirements, to prevent downstream tasks from having to check
            # for this special case.
            if invalidation_check.all_vts:
                target_set_id = VersionedTargetSet.from_versioned_targets(
                    invalidation_check.all_vts
                ).cache_key.hash
            else:
                target_set_id = "no_targets"

            # NB: Since PythonBinaryCreate is the only task that exports python code for use outside the
            # host system, it's the only python task that needs to resolve for non-'current'
            # platforms. PythonBinaryCreate will actually validate the platforms itself when resolving
            # requirements, instead of using this method, so we can always resolve for 'current' here in
            # order to pull in any binary or universal dists needed for the currently executing host.
            platforms = ["current"]

            path = os.path.realpath(
                os.path.join(self.workdir, str(interpreter.identity), target_set_id)
            )
            # Note that we check for the existence of the directory, instead of for invalid_vts,
            # to cover the empty case.
            if not os.path.isdir(path):
                with safe_concurrent_creation(path) as safe_path:
                    pex_builder = PexBuilderWrapper.Factory.create(
                        builder=PEXBuilder(path=safe_path, interpreter=interpreter, copy=True),
                        log=self.context.log,
                    )
                    pex_builder.add_requirement_libs_from(req_libs, platforms=platforms)
                    pex_builder.freeze()
        return PEX(path, interpreter=interpreter)

    def resolve_requirement_strings(self, interpreter, requirement_strings):
        """Resolve a list of pip-style requirement strings."""
        requirement_strings = sorted(requirement_strings)
        if len(requirement_strings) == 0:
            req_strings_id = "no_requirements"
        elif len(requirement_strings) == 1:
            req_strings_id = requirement_strings[0]
        else:
            req_strings_id = hash_all(requirement_strings)

        path = os.path.realpath(
            os.path.join(self.workdir, str(interpreter.identity), req_strings_id)
        )
        if not os.path.isdir(path):
            reqs = [PythonRequirement(req_str) for req_str in requirement_strings]
            with safe_concurrent_creation(path) as safe_path:
                pex_builder = PexBuilderWrapper.Factory.create(
                    builder=PEXBuilder(path=safe_path, interpreter=interpreter, copy=True),
                    log=self.context.log,
                )
                pex_builder.add_resolved_requirements(reqs)
                pex_builder.freeze()
        return PEX(path, interpreter=interpreter)

    @classmethod
    @contextmanager
    def merged_pex(cls, path, pex_info, interpreter, pexes, interpeter_constraints=None):
        """Yields a pex builder at path with the given pexes already merged.

        :rtype: :class:`pex.pex_builder.PEXBuilder`
        """
        pex_paths = [pex.path() for pex in pexes if pex]
        if pex_paths:
            pex_info = pex_info.copy()
            pex_info.merge_pex_path(":".join(pex_paths))

        with safe_concurrent_creation(path) as safe_path:
            builder = PEXBuilder(safe_path, interpreter, pex_info=pex_info)
            if interpeter_constraints:
                for constraint in interpeter_constraints:
                    builder.add_interpreter_constraint(constraint)
            yield builder

    @classmethod
    def merge_pexes(cls, path, pex_info, interpreter, pexes, interpeter_constraints=None):
        """Generates a merged pex at path."""
        with cls.merged_pex(path, pex_info, interpreter, pexes, interpeter_constraints) as builder:
            builder.freeze(bytecode_compile=False)
