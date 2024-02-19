# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Python.

See https://www.pantsbuild.org/docs/python-backend.
"""

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import (
    coverage_py,
    export,
    lockfile,
    lockfile_generation,
    package_dists,
    package_pex_binary,
    pytest_runner,
    repl,
    run_pex_binary,
    run_python_requirement,
    run_python_source,
    tailor,
)
from pants.backend.python.macros import (
    pipenv_requirements,
    poetry_requirements,
    python_requirements,
)
from pants.backend.python.macros.pipenv_requirements import PipenvRequirementsTargetGenerator
from pants.backend.python.macros.poetry_requirements import PoetryRequirementsTargetGenerator
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.subsystems import debugpy
from pants.backend.python.target_types import (
    PexBinariesGeneratorTarget,
    PexBinary,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourceField,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import (
    ancestor_files,
    local_dists,
    local_dists_pep660,
    pex,
    pex_from_targets,
    python_sources,
)
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target

wrap_python = wrap_source_rule_and_target(PythonSourceField, "python_sources")


def build_file_aliases():
    return BuildFileAliases(objects={"python_artifact": PythonArtifact, "setup_py": PythonArtifact})


def rules():
    return (
        *target_types_rules.rules(),
        # Subsystems
        *coverage_py.rules(),
        *debugpy.rules(),
        # Util rules
        *ancestor_files.rules(),
        *dependency_inference_rules.rules(),
        *local_dists_pep660.rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *python_sources.rules(),
        # Goals
        *package_pex_binary.rules(),
        *pytest_runner.rules(),
        *repl.rules(),
        *run_pex_binary.rules(),
        *run_python_requirement.rules(),
        *run_python_source.rules(),
        *package_dists.rules(),
        *tailor.rules(),
        *local_dists.rules(),
        *export.rules(),
        *lockfile.rules(),
        *lockfile_generation.rules(),
        # Macros.
        *pipenv_requirements.rules(),
        *poetry_requirements.rules(),
        *python_requirements.rules(),
        *wrap_python.rules,
    )


def target_types():
    return (
        PexBinary,
        PexBinariesGeneratorTarget,
        PythonDistribution,
        TargetGeneratorSourcesHelperTarget,
        PythonRequirementTarget,
        PythonSourcesGeneratorTarget,
        PythonSourceTarget,
        PythonTestsGeneratorTarget,
        PythonTestTarget,
        PythonTestUtilsGeneratorTarget,
        # Macros.
        PipenvRequirementsTargetGenerator,
        PoetryRequirementsTargetGenerator,
        PythonRequirementsTargetGenerator,
        *wrap_python.target_types,
    )
