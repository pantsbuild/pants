# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Python.

See https://www.pantsbuild.org/docs/python-backend.
"""

from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import (
    coverage_py,
    package_pex_binary,
    pytest_runner,
    repl,
    run_pex_binary,
    setup_py,
)
from pants.backend.python.macros.pants_requirement import PantsRequirement
from pants.backend.python.macros.pipenv_requirements import PipenvRequirements
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.macros.python_requirements import PythonRequirements
from pants.backend.python.subsystems import python_native_code
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonLibrary,
    PythonRequirementLibrary,
    PythonRequirementsFile,
    PythonTests,
)
from pants.backend.python.target_types import rules as target_type_rules
from pants.backend.python.util_rules import (
    ancestor_files,
    extract_pex,
    pex,
    pex_cli,
    pex_environment,
    pex_from_targets,
    python_sources,
)
from pants.build_graph.build_file_aliases import BuildFileAliases


def build_file_aliases():
    return BuildFileAliases(
        objects={"python_artifact": PythonArtifact, "setup_py": PythonArtifact},
        context_aware_object_factories={
            "python_requirements": PythonRequirements,
            "pipenv_requirements": PipenvRequirements,
            PantsRequirement.alias: PantsRequirement,
        },
    )


def rules():
    return (
        *coverage_py.rules(),
        *ancestor_files.rules(),
        *extract_pex.rules(),
        *python_sources.rules(),
        *dependency_inference_rules.rules(),
        *pex.rules(),
        *pex_cli.rules(),
        *pex_environment.rules(),
        *pex_from_targets.rules(),
        *pytest_runner.rules(),
        *package_pex_binary.rules(),
        *python_native_code.rules(),
        *repl.rules(),
        *run_pex_binary.rules(),
        *target_type_rules(),
        *setup_py.rules(),
    )


def target_types():
    return [
        PexBinary,
        PythonDistribution,
        PythonLibrary,
        PythonRequirementLibrary,
        PythonRequirementsFile,
        PythonTests,
    ]
