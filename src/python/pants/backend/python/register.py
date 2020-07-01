# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Python.

See https://pants.readme.io/docs/python-backend.
"""

from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.pants_requirement import PantsRequirement
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.python_requirements import PythonRequirements
from pants.backend.python.rules import (
    coverage,
    download_pex_bin,
    inject_init,
    pex,
    pex_from_targets,
    pytest_runner,
    python_create_binary,
    python_sources,
    repl,
    run_setup_py,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.target_types import (
    PythonBinary,
    PythonLibrary,
    PythonRequirementLibrary,
    PythonRequirementsFile,
    PythonTests,
)
from pants.backend.python.targets.python_binary import PythonBinary as PythonBinaryV1
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.backend.python.targets.python_requirement_library import (
    PythonRequirementLibrary as PythonRequirementLibraryV1,
)
from pants.backend.python.targets.python_requirements_file import (
    PythonRequirementsFile as PythonRequirementsFileV1,
)
from pants.backend.python.targets.python_tests import PythonTests as PythonTestsV1
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_requirement import PythonRequirement


def global_subsystems():
    return {
        python_native_code.PythonNativeCode,
        subprocess_environment.SubprocessEnvironment,
        PexBuilderWrapper.Factory,
    }


def build_file_aliases():
    return BuildFileAliases(
        targets={
            PythonBinaryV1.alias(): PythonBinaryV1,
            PythonLibraryV1.alias(): PythonLibraryV1,
            PythonTestsV1.alias(): PythonTestsV1,
            "python_requirement_library": PythonRequirementLibraryV1,
            PythonRequirementsFileV1.alias(): PythonRequirementsFileV1,
        },
        objects={
            "python_requirement": PythonRequirement,
            "python_artifact": PythonArtifact,
            "setup_py": PythonArtifact,
        },
        context_aware_object_factories={
            "python_requirements": PythonRequirements,
            PantsRequirement.alias: PantsRequirement,
        },
    )


def rules():
    return (
        *coverage.rules(),
        *download_pex_bin.rules(),
        *inject_init.rules(),
        *python_sources.rules(),
        *dependency_inference_rules.rules(),
        *module_mapper.rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *pytest_runner.rules(),
        *python_create_binary.rules(),
        *python_native_code.rules(),
        *repl.rules(),
        *run_setup_py.rules(),
        *subprocess_environment.rules(),
    )


def target_types():
    return [
        PythonBinary,
        PythonLibrary,
        PythonRequirementLibrary,
        PythonRequirementsFile,
        PythonTests,
    ]
