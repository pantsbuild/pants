# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonRequirementFindLinksField,
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


class PantsRequirementsTestutilField(BoolField):
    alias = "testutil"
    default = True
    help = "If true, include `pantsbuild.pants.testutil` to write tests for your plugin."


class PantsRequirementsVersionSpecField(StringField):
    alias = "version_spec"
    default = f"== {PANTS_SEMVER.public}"
    help = help_text(
        """
        The PEP 440 version specifier version of Pants to target.
        E.g. `== 2.15.*`, or `>= 2.16.0, < 2.17.0`
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
        PantsRequirementsVersionSpecField,
        PantsRequirementsTestutilField,
        PythonRequirementFindLinksField,
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
    version_spec = generator[PantsRequirementsVersionSpecField].value

    def create_tgt(dist: str, module: str) -> PythonRequirementTarget:
        return PythonRequirementTarget(
            {
                PythonRequirementsField.alias: (f"{dist} {version_spec}",),
                PythonRequirementFindLinksField.alias: ("https://wheels.pantsbuild.org/simple",),
                PythonRequirementModulesField.alias: (module,),
                **request.template,
            },
            request.template_address.create_generated(dist),
            union_membership,
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
