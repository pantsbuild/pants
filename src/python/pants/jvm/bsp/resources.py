# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.build_root import BuildRoot
from pants.bsp.spec.base import BuildTargetIdentifier
from pants.bsp.util_rules.targets import BSPResourcesRequest, BSPResourcesResult
from pants.core.target_types import ResourceSourceField
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix
from pants.engine.internals.graph import resolve_coarsened_targets
from pants.engine.intrinsics import add_prefix
from pants.engine.rules import collect_rules, implicitly
from pants.engine.target import SourcesField
from pants.util.strutil import path_safe


def _jvm_resources_directory(target_id: BuildTargetIdentifier) -> str:
    # TODO: Currently, we have a single BuildTarget per group, and so we include the transitive
    # resource dependencies in one owning directory. As part of #15051 we'll likely need to find
    # "owning" BuildTargets for each resources target in order to avoid having all of them
    # emit the transitive resources.
    return f"jvm/resources/{path_safe(target_id.uri)}"


async def _jvm_bsp_resources(
    request: BSPResourcesRequest,
    build_root: BuildRoot,
) -> BSPResourcesResult:
    """Generically handles a BSPResourcesRequest (subclass).

    This is a rule helper rather than a `@rule` for the same reason as `_jvm_bsp_compile`.
    """
    coarsened_tgts = await resolve_coarsened_targets(
        **implicitly(Addresses([fs.address for fs in request.field_sets]))
    )

    source_files = await strip_source_roots(
        **implicitly(
            SourceFilesRequest(
                [tgt.get(SourcesField) for tgt in coarsened_tgts.closure()],
                for_sources_types=(ResourceSourceField,),
                enable_codegen=True,
            )
        )
    )

    rel_resources_dir = _jvm_resources_directory(request.bsp_target.bsp_target_id)
    output_digest = await add_prefix(
        AddPrefix(source_files.snapshot.digest, rel_resources_dir),
    )

    return BSPResourcesResult(
        resources=(
            # NB: IntelliJ requires that directory URIs end in slashes.
            build_root.pathlib_path.joinpath(".pants.d/bsp", rel_resources_dir).as_uri() + "/",
        ),
        output_digest=output_digest,
    )


def rules():
    return [
        *collect_rules(),
        *stripped_source_files.rules(),
    ]
