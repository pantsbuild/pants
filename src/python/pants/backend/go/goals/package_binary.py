# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.target_type_rules import (
    GoBinaryMainImportPathRequest,
    resolve_go_binary_main_import_path,
)
from pants.backend.go.target_types import (
    GoBinaryMainImportPathField,
    GoBinaryMainPackageField,
    GoBinaryTarget,
    GoPackageTarget,
    GoThirdPartyModuleTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules.binary import (
    GoBinaryMainPackageRequest,
    determine_main_pkg_for_go_binary,
)
from pants.backend.go.util_rules.build_opts import (
    GoBuildOptionsFromTargetRequest,
    go_extract_build_options_from_target,
)
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    MergeBuiltGoPackageArchivesRequest,
    merge_built_go_package_archives,
    required_built_go_package,
)
from pants.backend.go.util_rules.build_pkg_target import BuildGoPackageTargetRequest
from pants.backend.go.util_rules.build_pkg_third_party import (
    BuildGoPackageRequestForThirdPartyPackageRequest,
    setup_build_go_package_target_request_for_third_party,
)
from pants.backend.go.util_rules.first_party_pkg import (
    FirstPartyPkgAnalysisRequest,
    analyze_first_party_package,
)
from pants.backend.go.util_rules.go_mod import GoModInfoRequest, determine_go_mod_info
from pants.backend.go.util_rules.link import LinkGoBinaryRequest, link_go_binary
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysisRequest,
    extract_package_info,
)
from pants.core.environments.target_types import EnvironmentField
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.engine.fs import AddPrefix
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (GoBinaryMainPackageField,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    main: GoBinaryMainPackageField
    main_import_path: GoBinaryMainImportPathField
    output_path: OutputPathField
    environment: EnvironmentField


@rule(desc="Package Go binary", level=LogLevel.DEBUG)
async def package_go_binary(field_set: GoBinaryFieldSet) -> BuiltPackage:
    main_pkg_get = (
        resolve_go_binary_main_import_path(
            GoBinaryMainImportPathRequest(field_set.address), **implicitly()
        )
        if field_set.main_import_path.value
        else determine_main_pkg_for_go_binary(GoBinaryMainPackageRequest(field_set.main))
    )
    main_pkg, build_opts = await concurrently(
        main_pkg_get,
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(field_set.address), **implicitly()
        ),
    )

    if main_pkg.is_third_party:
        assert isinstance(main_pkg.import_path, str)

        go_mod_address = main_pkg.address.maybe_convert_to_target_generator()
        go_mod_info = await determine_go_mod_info(GoModInfoRequest(go_mod_address))

        analysis = await extract_package_info(
            ThirdPartyPkgAnalysisRequest(
                main_pkg.import_path,
                go_mod_address,
                go_mod_info.digest,
                go_mod_info.mod_path,
                build_opts=build_opts,
            ),
            **implicitly(),
        )

        package_name = analysis.name
    else:
        main_pkg_analysis = await analyze_first_party_package(
            FirstPartyPkgAnalysisRequest(main_pkg.address, build_opts=build_opts), **implicitly()
        )
        if not main_pkg_analysis.analysis:
            raise ValueError(
                f"Unable to analyze main package `{main_pkg.address}` for go_binary target {field_set.address}: {main_pkg_analysis.stderr}"
            )

        package_name = main_pkg_analysis.analysis.name

    if package_name != "main":
        if main_pkg.is_third_party_module:
            main_alias = GoThirdPartyModuleTarget.alias
        elif main_pkg.is_third_party:
            main_alias = GoThirdPartyPackageTarget.alias
        else:
            main_alias = GoPackageTarget.alias
        raise ValueError(
            f"`{main_alias}` target `{main_pkg.address}` is used as the main package for "
            f"{GoBinaryTarget.alias} target `{field_set.address}` but uses package name "
            f"`{package_name}` instead of `main`. Go requires that main packages actually use "
            "`main` as the package name."
        )

    if main_pkg.is_third_party_module:
        assert isinstance(main_pkg.import_path, str)
        fallible_request = await setup_build_go_package_target_request_for_third_party(
            BuildGoPackageRequestForThirdPartyPackageRequest(
                import_path=main_pkg.import_path,
                go_mod_address=go_mod_address,
                build_opts=build_opts,
                is_main=True,
            )
        )
        build_request = fallible_request.request
        if build_request is None:
            raise ValueError(
                f"Unable to build main package `{main_pkg.import_path}` for "
                f"{GoBinaryTarget.alias} target `{field_set.address}`: {fallible_request.stderr}"
            )
        built_package = await required_built_go_package(
            **implicitly({build_request: BuildGoPackageRequest})
        )
    else:
        built_package = await required_built_go_package(
            **implicitly(
                BuildGoPackageTargetRequest(main_pkg.address, is_main=True, build_opts=build_opts)
            ),
        )
    merged = await merge_built_go_package_archives(
        MergeBuiltGoPackageArchivesRequest((built_package,))
    )

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    binary = await link_go_binary(
        LinkGoBinaryRequest(
            input_digest=merged.digest,
            archives=(built_package.pkg_archive_path,),
            build_opts=build_opts,
            import_paths_to_pkg_a_files=merged.import_paths_to_pkg_a_files,
            output_filename=f"./{output_filename.name}",
            description=f"Link Go binary for {field_set.address}",
        ),
        **implicitly(),
    )

    renamed_output_digest = await add_prefix(AddPrefix(binary.digest, str(output_filename.parent)))

    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(renamed_output_digest, (artifact,))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, GoBinaryFieldSet)]
