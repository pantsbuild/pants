# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Dict, Optional

from pex.interpreter import PythonInterpreter
from pex.pex import PEX

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.build_graph.files import Files
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.python.python_setup import PythonSetup
from pants.util.contextutil import temporary_file


def ensure_interpreter_search_path_env(interpreter):
    """Produces an environment dict that ensures that the given interpreter is discovered at
    runtime.

    At pex build time, if any interpreter constraints are specified (e.g.: 'CPython>=2.7,<3'), they
    are added to the resulting pex binary's metadata. At runtime, pex will apply those constraints to
    locate a relevant interpreter on the `PATH`. If `PEX_PYTHON_PATH` is set in the environment, it
    will be used instead of a `PATH` search. Unlike a typical `PATH`, `PEX_PYTHON_PATH` can contain a
    mix of files and directories. We exploit this to set up a singular `PEX_PYTHON_PATH` pointing
    directly at the given `interpreter` (which should match the constraints that were provided at
    build time).

    Subclasses of PythonExecutionTaskBase can use `self.ensure_interpreter_search_path_env` to get the
    relevant interpreter, but this function is exposed for cases where the building of the pex is
    separated from the execution of the pex.
    """
    chosen_interpreter_binary_path = interpreter.binary
    return {
        "PEX_IGNORE_RCFILES": "1",
        "PEX_PYTHON_PATH": chosen_interpreter_binary_path,
    }


class PythonExecutionTaskBase(ResolveRequirementsTaskBase):
    """Base class for tasks that execute user Python code in a PEX environment.

    Note: Extends ResolveRequirementsTaskBase because it may need to resolve
    extra requirements in order to execute the code.
    """

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(PythonInterpreter)
        round_manager.require_data(ResolveRequirements.REQUIREMENTS_PEX)
        round_manager.require_data(GatherSources.PYTHON_SOURCES)

    def extra_requirements(self):
        """Override to provide extra requirements needed for execution.

        :returns: An iterable of pip-style requirement strings.
        :rtype: :class:`collections.Iterable` of str
        """
        return ()

    @dataclass(frozen=True)
    class ExtraFile:
        """Models an extra file to place in a PEX."""

        path: str
        content: bytes

        @classmethod
        def empty(cls, path):
            """Creates an empty file with the given PEX path.

            :param str path: The path this extra file should have when added to a PEX.
            :rtype: :class:`ExtraFile`
            """
            return cls(path=path, content=b"")

        def add_to(self, builder):
            """Adds this extra file to a PEX builder.

            :param builder: The PEX builder to add this extra file to.
            :type builder: :class:`pex.pex_builder.PEXBuilder`
            """
            with temporary_file() as fp:
                fp.write(self.content)
                fp.close()
                add = builder.add_source if self.path.endswith(".py") else builder.add_resource
                add(fp.name, self.path)

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PythonSetup,)

    def extra_files(self):
        """Override to provide extra files needed for execution.

        :returns: An iterable of extra files to add to the PEX.
        :rtype: :class:`collections.Iterable` of :class:`PythonExecutionTaskBase.ExtraFile`
        """
        return ()

    def prepare_pex_env(self, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Prepares an environment that will run this task's pex with proper isolation.

        :param env: An optional seed environment to use; os.environ by default.
        :return: An environment dict for use in running a PEX.
        """
        env = (env or os.environ).copy()

        interpreter = self.context.products.get_data(PythonInterpreter)
        interpreter_search_path_env = ensure_interpreter_search_path_env(interpreter)
        env.update(interpreter_search_path_env)

        return env

    def create_pex(self, pex_info=None):
        """Returns a wrapped pex that "merges" other pexes produced in previous tasks via PEX_PATH.

        This method always creates a PEX to run locally on the current platform and selected
        interpreter: to create a pex that is distributable to other environments, use the pex_build_util
        Subsystem.

        The returned pex will have the pexes from the ResolveRequirements and GatherSources tasks mixed
        into it via PEX_PATH. Any 3rdparty requirements declared with self.extra_requirements() will
        also be resolved for the global interpreter, and added to the returned pex via PEX_PATH.

        :param pex_info: An optional PexInfo instance to provide to self.merged_pex().
        :type pex_info: :class:`pex.pex_info.PexInfo`, or None
        task. Otherwise, all of the interpreter constraints from all python targets will applied.
        :rtype: :class:`pex.pex.PEX`
        """
        relevant_targets = self.context.targets(
            lambda tgt: isinstance(
                tgt, (PythonDistribution, PythonRequirementLibrary, PythonTarget, Files)
            )
        )
        with self.invalidated(relevant_targets) as invalidation_check:

            # If there are no relevant targets, we still go through the motions of resolving
            # an empty set of requirements, to prevent downstream tasks from having to check
            # for this special case.
            if invalidation_check.all_vts:
                target_set_id = VersionedTargetSet.from_versioned_targets(
                    invalidation_check.all_vts
                ).cache_key.hash
            else:
                target_set_id = "no_targets"

            interpreter = self.context.products.get_data(PythonInterpreter)
            path = os.path.realpath(
                os.path.join(self.workdir, str(interpreter.identity), target_set_id)
            )

            # Note that we check for the existence of the directory, instead of for invalid_vts,
            # to cover the empty case.
            if not os.path.isdir(path):
                pexes = [
                    self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX),
                    self.context.products.get_data(GatherSources.PYTHON_SOURCES),
                ]

                if self.extra_requirements():
                    extra_requirements_pex = self.resolve_requirement_strings(
                        interpreter, self.extra_requirements()
                    )
                    # Add the extra requirements first, so they take precedence over any colliding version
                    # in the target set's dependency closure.
                    pexes = [extra_requirements_pex] + pexes

                # NB: See docstring. We always use the previous selected interpreter.
                constraints = {str(interpreter.identity.requirement)}

                with self.merged_pex(path, pex_info, interpreter, pexes, constraints) as builder:
                    for extra_file in self.extra_files():
                        extra_file.add_to(builder)
                    builder.freeze(bytecode_compile=False)

        return PEX(path, interpreter)
