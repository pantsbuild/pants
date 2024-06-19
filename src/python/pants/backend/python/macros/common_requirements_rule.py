# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from typing import Callable, Iterable, cast

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.goals.lockfile import synthetic_lockfile_target_name
from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonRequirementTypeStubModulesField,
)
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.rules import Get
from pants.engine.target import (
    Dependencies,
    GenerateTargetsRequest,
    InvalidFieldException,
    SingleSourceField,
)
from pants.engine.unions import UnionMembership
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)
ParseRequirementsCallback = Callable[[bytes, str], Iterable[PipRequirement]]


async def _generate_requirements(
    request: GenerateTargetsRequest,
    union_membership: UnionMembership,
    python_setup: PythonSetup,
    parse_requirements_callback: ParseRequirementsCallback,
) -> Iterable[PythonRequirementTarget]:
    generator = request.generator
    requirements_rel_path = generator[SingleSourceField].value
    requirements_full_path = generator[SingleSourceField].file_path
    overrides = {
        canonicalize_project_name(k): v
        for k, v in request.require_unparametrized_overrides().items()
    }

    # Pretend this is just another generated target, for typing purposes.
    file_tgt = cast(
        "PythonRequirementTarget",
        TargetGeneratorSourcesHelperTarget(
            {TargetGeneratorSourcesHelperSourcesField.alias: requirements_rel_path},
            Address(
                request.template_address.spec_path,
                target_name=request.template_address.target_name,
                relative_file_path=requirements_rel_path,
            ),
            union_membership,
        ),
    )

    req_deps = [file_tgt.address.spec]

    resolve = request.template.get(
        PythonRequirementResolveField.alias, python_setup.default_resolve
    )
    lockfile = (
        python_setup.resolves.get(resolve) if python_setup.enable_synthetic_lockfiles else None
    )
    if lockfile:
        lockfile_address = Address(
            os.path.dirname(lockfile),
            target_name=synthetic_lockfile_target_name(resolve),
        )
        target_adaptor = await Get(
            TargetAdaptor,
            TargetAdaptorRequest(
                description_of_origin=f"{generator.alias} lockfile dep for the {resolve} resolve",
                address=lockfile_address,
            ),
        )
        if target_adaptor.type_alias == "_lockfiles":
            req_deps.append(f"{lockfile}:{synthetic_lockfile_target_name(resolve)}")
        else:
            logger.warning(
                softwrap(
                    f"""
                    The synthetic lockfile target for {lockfile} is being shadowed by the
                    {target_adaptor.type_alias} target {lockfile_address}.

                    There will not be any dependency to the lockfile.

                    Resolve by either renaming the shadowing target, the resolve {resolve!r} or
                    moving the target or the lockfile to another directory.
                    """
                )
            )

    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            [requirements_full_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{generator}'s field `{SingleSourceField.alias}`",
        ),
    )

    module_mapping = generator[ModuleMappingField].value
    stubs_mapping = generator[TypeStubsModuleMappingField].value

    def generate_tgt(
        project_name: str, parsed_reqs: Iterable[PipRequirement]
    ) -> PythonRequirementTarget:
        normalized_proj_name = canonicalize_project_name(project_name)
        tgt_overrides = overrides.pop(normalized_proj_name, {})
        if Dependencies.alias in tgt_overrides:
            tgt_overrides = tgt_overrides | {
                Dependencies.alias: list(tgt_overrides[Dependencies.alias]) + req_deps
            }

        return PythonRequirementTarget(
            {
                **request.template,
                PythonRequirementsField.alias: list(parsed_reqs),
                PythonRequirementModulesField.alias: module_mapping.get(normalized_proj_name),
                PythonRequirementTypeStubModulesField.alias: stubs_mapping.get(
                    normalized_proj_name
                ),
                # This may get overridden by `tgt_overrides`, which will have already added in
                # the file tgt.
                Dependencies.alias: req_deps,
                **tgt_overrides,
            },
            request.template_address.create_generated(project_name),
            union_membership,
        )

    requirements = parse_requirements_callback(digest_contents[0].content, requirements_full_path)
    grouped_requirements = itertools.groupby(
        requirements, lambda parsed_req: parsed_req.project_name
    )
    result = tuple(
        generate_tgt(project_name, parsed_reqs_)
        for project_name, parsed_reqs_ in grouped_requirements
    ) + (file_tgt,)

    if overrides:
        raise InvalidFieldException(
            softwrap(
                f"""
                Unused key in the `overrides` field for {request.template_address}:
                {sorted(overrides)}
                """
            )
        )

    return result
