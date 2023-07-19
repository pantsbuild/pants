# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from typing import Iterable

from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTarget,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    GeneratedTargets,
    GenerateTargetsRequest,
    StringField,
    TargetGenerator,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.strutil import help_text
from pants.version import PANTS_SEMVER

PY = f"{sys.version_info.major}{sys.version_info.minor}"

# NB: List of platforms comes from `src/python/pants_release/generate_github_workflows.py`
#   we likely shouldn't ever remove a platform.
PANTS_WHEEL_PLATFORMS = [
    (
        f"cp{PY}-cp{PY}-manylinux2014_x86_64",
        ('sys_platform == "linux"', 'platform_machine == "x86_64"'),
    ),
    (
        f"cp{PY}-cp{PY}-manylinux2014_aarch64",
        ('sys_platform == "linux"', 'platform_machine == "aarch64"'),
    ),
    (
        f"cp{PY}-cp{PY}-macosx_10_15_x86_64",
        (
            'sys_platform == "darwin"',
            'platform_machine == "x86_64"',
            'platform_release == "10.15"',
        ),
    ),
    (
        f"cp{PY}-cp{PY}-macosx_10_16_x86_64",
        (
            'sys_platform == "darwin"',
            'platform_machine == "x86_64"',
            'platform_release == "10.16"',
        ),
    ),
    (
        f"cp{PY}-cp{PY}-macosx_11_0_x86_64",
        (
            'sys_platform == "darwin"',
            'platform_machine == "x86_64"',
            'platform_release == "11.0"',
        ),
    ),
    (
        f"cp{PY}-cp{PY}-macosx_11_0_arm64",
        (
            'sys_platform == "darwin"',
            'platform_machine == "arm64"',
            'platform_release == "11.0"',
        ),
    ),
]

class PantsRequirementsTestutilField(BoolField):
    alias = "testutil"
    default = True
    help = "If true, include `pantsbuild.pants.testutil` to write tests for your plugin."


class PantsRequirementsVersionField(StringField):
    alias = "version"
    default = PANTS_SEMVER.public
    help = help_text(
        """
        The version of Pants to target.
        This must be a full release version (e.g. 2.16.0 or 2.15.0.dev5).
        """
    )

class PantsRequirementsTargetGenerator(TargetGenerator):
    alias = "pants_requirements"
    help = help_text(
        """
        Generate `python_requirement` targets for Pants itself to use with Pants plugins.

        This is useful when writing plugins so that you can build and test your
        plugin using Pants.

        The generated targets will have the correct version based on the exact `version` in your
        `pants.toml`, and they will work with dependency inference. They're pulled directly from
        our GitHub releases, using the relevant platform markers.

        (If this versioning scheme does not work for you, you can directly create
        `python_requirement` targets for `pantsbuild.pants` and `pantsbuild.pants.testutil`. We
        also invite you to share your ideas at
        https://github.com/pantsbuild/pants/issues/new/choose)
        """
    )
    generated_target_cls = PythonRequirementTarget
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PantsRequirementsVersionField,
        PantsRequirementsTestutilField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonRequirementResolveField,)


class GenerateFromPantsRequirementsRequest(GenerateTargetsRequest):
    generate_from = PantsRequirementsTargetGenerator



@rule
def generate_from_pants_requirements(
    request: GenerateFromPantsRequirementsRequest, union_membership: UnionMembership
) -> GeneratedTargets:
    generator = request.generator
    version = generator[PantsRequirementsVersionField].value

    def create_tgt(dist: str, module: str, platforms: Iterable[tuple[str, Iterable[str]]]) -> PythonRequirementTarget:
        def maybe_markers(markers):
            if not markers:
                return ""
            return f"; {' and '.join(markers)}"
        return PythonRequirementTarget(
            {
                PythonRequirementsField.alias: (
                    f"{dist} @ https://github.com/pantsbuild/pants/releases/download/release_{version}/{dist}-{version}-{plat_tag}.whl {maybe_markers(markers)}"
                    for plat_tag, markers in platforms
                ),
                PythonRequirementModulesField.alias: (module,),
                **request.template,
            },
            request.template_address.create_generated(dist),
            union_membership,
        )

    result = [create_tgt("pantsbuild.pants", "pants", PANTS_WHEEL_PLATFORMS)]
    if generator[PantsRequirementsTestutilField].value:
        result.append(create_tgt("pantsbuild.pants.testutil", "pants.testutil", [("py3-none-any", [])]))
    return GeneratedTargets(generator, result)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPantsRequirementsRequest),
    )
