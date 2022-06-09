# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen import export_codegen_goal
from pants.backend.python.goals import publish
from pants.backend.python.subsystems import setuptools_scm, twine
from pants.backend.python.target_types import VCSVersion
from pants.backend.python.util_rules import pex, vcs_versioning


def rules():
    return (
        *pex.rules(),
        *publish.rules(),
        *vcs_versioning.rules(),
        *setuptools_scm.rules(),
        *export_codegen_goal.rules(),
        *twine.rules(),
    )


def target_types():
    return (VCSVersion,)
