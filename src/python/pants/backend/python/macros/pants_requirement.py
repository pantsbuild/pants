# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, cast

from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementsField,
    PythonRequirementTarget,
)
from pants.base.build_environment import pants_version
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    GeneratedTargets,
    GenerateTargetsRequest,
    InvalidFieldException,
    StringField,
    Target,
)
from pants.engine.unions import UnionRule


class PantsDistField(StringField):
    alias = "dist"
    default = "pantsbuild.pants"
    help = (
        "The Pants distribution. Must start with `pantsbuild.`, e.g. `pantsbuild.pants.testutil`."
    )
    value: str

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> str:
        value_or_default = cast(str, super().compute_value(raw_value, address))
        if value_or_default != "pantsbuild.pants" and not value_or_default.startswith(
            "pantsbuild.pants."
        ):
            raise InvalidFieldException(
                f"The `{cls.alias}` field in target {address} must be `pantsbuild.pants` or "
                f"start with `pantsbuild.pants.`, but it was: `{value_or_default}`."
            )
        return value_or_default


class PantsModulesField(PythonRequirementModulesField):
    help = (
        "The modules exposed by the dist, e.g. `['pants.testutil']`.\n\n"
        "This defaults to the name of the dist without the leading `pantsbuild`."
    )


class PantsRequirementTargetGenerator(Target):
    alias = "pants_requirement"
    help = (
        "Generate a `python_requirement` target for Pants distributions using your current Pants "
        "version.\n\n"
        "This requirement is useful when writing plugins so that you can build and test your "
        "plugin using Pants. Using the resulting target as a dependency of their plugin target "
        "ensures the project version of Pants.\n\n"
        "Note: the requirement generated is for official Pants releases on PyPI; so may not be "
        "appropriate for use in a repo that uses custom Pants dists."
    )
    core_fields = (*COMMON_TARGET_FIELDS, PantsDistField, PantsModulesField)


class GenerateFromPantsRequirementRequest(GenerateTargetsRequest):
    generate_from = PantsRequirementTargetGenerator


@rule
def generate_from_pants_requirement(
    request: GenerateFromPantsRequirementRequest,
) -> GeneratedTargets:
    generator = request.generator
    dist = generator[PantsDistField].value
    modules = generator[PantsModulesField].value or [dist.replace("pantsbuild.", "")]
    tgt = PythonRequirementTarget(
        {
            PythonRequirementsField.alias: [f"{dist}=={pants_version()}"],
            PythonRequirementModulesField.alias: modules,
        },
        generator.address.create_generated(dist),
    )
    return GeneratedTargets(generator, [tgt])


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPantsRequirementRequest),
    )
