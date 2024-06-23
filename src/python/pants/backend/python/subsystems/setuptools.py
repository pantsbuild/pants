# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import PythonProvidesField
from pants.core.goals.package import PackageFieldSet
from pants.engine.rules import collect_rules


@dataclass(frozen=True)
class PythonDistributionFieldSet(PackageFieldSet):
    required_fields = (PythonProvidesField,)

    provides: PythonProvidesField


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help_short = "Python setuptools, used to package `python_distribution` targets."

    default_requirements = ["setuptools>=63.1.0,<64.0", "wheel>=0.35.1,<0.38"]

    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools.lock")


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
    )
