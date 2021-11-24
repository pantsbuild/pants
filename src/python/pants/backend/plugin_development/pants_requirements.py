# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementsField,
    PythonRequirementTarget,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    GeneratedTargets,
    GenerateTargetsRequest,
    Target,
)
from pants.engine.unions import UnionRule
from pants.version import MAJOR_MINOR, PANTS_SEMVER


class PantsRequirementsTestutilField(BoolField):
    alias = "testutil"
    default = True
    help = "If true, include `pantsbuild.pants.testutil` to write tests for your plugin."


class PantsRequirementsTargetGenerator(Target):
    alias = "pants_requirements"
    help = (
        "Generate `python_requirement` targets for Pants itself to use with Pants plugins.\n\n"
        "This is useful when writing plugins so that you can build and test your "
        "plugin using Pants. The generated targets will have the correct version based on the "
        "`version` in your `pants.toml`, and they will work with dependency inference.\n\n"
        "Because the Plugin API is not yet stable, the version is set automatically for you "
        "to improve stability. If you're currently using a dev release, the version will be set to "
        "that exact dev release. If you're using a release candidate (rc) or stable release, the "
        "version will allow any non-dev-release release within the release series, e.g. "
        f"`>={MAJOR_MINOR}.0rc0,<{PANTS_SEMVER.major}.{PANTS_SEMVER.minor + 1}`.\n\n"
        "(If this versioning scheme does not work for you, you can directly create "
        "`python_requirement` targets for `pantsbuild.pants` and `pantsbuild.pants.testutil`. We "
        "also invite you to share your ideas at "
        "https://github.com/pantsbuild/pants/issues/new/choose)"
    )
    core_fields = (*COMMON_TARGET_FIELDS, PantsRequirementsTestutilField)


class GenerateFromPantsRequirementsRequest(GenerateTargetsRequest):
    generate_from = PantsRequirementsTargetGenerator


def determine_version() -> str:
    # Because the Plugin API is not stable, it can have breaking changes in-between dev releases.
    # Technically, it can also have breaking changes between rcs in the same release series, but
    # this is much less likely.
    #
    # So, we require exact matches when developing against a dev release, but only require
    # matching the release series if on an rc or stable release.
    #
    # If this scheme does not work for users, they can:
    #
    #    1. Use a `python_requirement` directly
    #    2. Add a new `version` field to this target generator.
    #    3. Fork this target generator.
    return (
        f"=={PANTS_SEMVER}"
        if PANTS_SEMVER.is_devrelease
        else (
            f">={PANTS_SEMVER.major}.{PANTS_SEMVER.minor}.0rc0,"
            f"<{PANTS_SEMVER.major}.{PANTS_SEMVER.minor + 1}"
        )
    )


@rule
def generate_from_pants_requirements(
    request: GenerateFromPantsRequirementsRequest,
) -> GeneratedTargets:
    generator = request.generator
    version = determine_version()

    def create_tgt(dist: str, module: str) -> PythonRequirementTarget:
        return PythonRequirementTarget(
            {
                PythonRequirementsField.alias: (f"{dist}{version}",),
                PythonRequirementModulesField.alias: (module,),
            },
            generator.address.create_generated(dist),
        )

    result = [create_tgt("pantsbuild.pants", "pants")]
    if generator[PantsRequirementsTestutilField].value:
        result.append(create_tgt("pantsbuild.pants.testutil", "pants.testutil"))
    return GeneratedTargets(generator, result)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPantsRequirementsRequest),
    )
