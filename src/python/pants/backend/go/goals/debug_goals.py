# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.go.target_types import (
    GoImportPathField,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules import first_party_pkg, third_party_pkg
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FirstPartyPkgAnalysisRequest,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets


class ShowGoPackageAnalysisSubsystem(GoalSubsystem):
    name = "go-show-package-analysis"
    help = "Show the package analysis for Go package targets."


class ShowGoPackageAnalysis(Goal):
    subsystem_cls = ShowGoPackageAnalysisSubsystem


@goal_rule
async def go_show_package_analysis(targets: Targets, console: Console) -> ShowGoPackageAnalysis:
    first_party_analysis_gets = []
    third_party_analysis_gets = []

    for target in targets:
        if target.has_field(GoPackageSourcesField):
            first_party_analysis_gets.append(
                Get(FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(target.address))
            )
        elif target.has_field(GoThirdPartyPackageDependenciesField):
            import_path = target[GoImportPathField].value
            go_mod_address = target.address.maybe_convert_to_target_generator()
            go_mod_info = await Get(GoModInfo, GoModInfoRequest(go_mod_address))
            third_party_analysis_gets.append(
                Get(
                    ThirdPartyPkgAnalysis,
                    ThirdPartyPkgAnalysisRequest(
                        import_path, go_mod_info.digest, go_mod_info.mod_path
                    ),
                )
            )

    first_party_analysis_results = await MultiGet(first_party_analysis_gets)
    third_party_analysis_results = await MultiGet(third_party_analysis_gets)

    for first_party_analysis_result in first_party_analysis_results:
        if first_party_analysis_result.analysis:
            console.write_stdout(str(first_party_analysis_result.analysis) + "\n")
        else:
            console.write_stdout(
                f"Error for {first_party_analysis_result.import_path}: {first_party_analysis_result.stderr}\n"
            )

    for third_party_analysis in third_party_analysis_results:
        if third_party_analysis.error:
            console.write_stdout(
                f"Error for {third_party_analysis.import_path}: {third_party_analysis.error}\n"
            )
        else:
            console.write_stdout(str(third_party_analysis) + "\n")

    return ShowGoPackageAnalysis(exit_code=0)


def rules():
    return (
        *collect_rules(),
        *first_party_pkg.rules(),
        *third_party_pkg.rules(),
    )
