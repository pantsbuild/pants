# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

from pants.backend.terraform.target_types import TerraformModuleSources
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.tailor import group_by_dir
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.option.custom_types import shell_str


class TerraformRunSubsystem(GoalSubsystem):
    name = "tf-run"
    help = "Run a Terraform command against a Terraform module."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Terraform arguments including the command",
        )
        register(
            "--capture-caches",
            type=bool,
            default=False,
            help="Save any changes to the Terraform caches including lockfile to repository.",
        )


class TerraformRunGoal(Goal):
    subsystem_cls = TerraformRunSubsystem


@goal_rule
async def run_terraform_command(
    targets: Targets, tf_run: TerraformRunSubsystem, console: Console, workspace: Workspace
) -> TerraformRunGoal:
    terraform_targets = [tgt for tgt in targets if tgt.has_field(TerraformModuleSources)]
    if len(terraform_targets) == 0:
        console.write_stdout("Nothing to do. No `terraform_module` targets were specified.\n")
        return TerraformRunGoal(exit_code=1)
    elif len(terraform_targets) > 1:
        raise ValueError(
            "Multiple `terraform_module` targets were specified. For safety, the `tf` goal intentionally "
            f"will only operate on one module at a time. The targets specified were: {', '.join(str(tgt.address) for tgt in terraform_targets)}"
        )

    terraform_target = terraform_targets[0]

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([terraform_target.address])
    )
    transitive_terraform_targets = [
        tgt for tgt in transitive_targets.closure if tgt.has_field(TerraformModuleSources)
    ]

    all_targets_to_hydrate_sources = (terraform_target,) + tuple(transitive_terraform_targets)
    hydrated_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(TerraformModuleSources), for_sources_types=(TerraformModuleSources,)
            ),
        )
        for tgt in all_targets_to_hydrate_sources
    )

    input_digest = await Get(Digest, MergeDigests([s.snapshot.digest for s in hydrated_sources]))

    # Get the main source directory for the `terraform_module`.
    # Given target generation, it may not be the tgt.address.spec_path. :(
    all_source_dirs = group_by_dir(hydrated_sources[0].snapshot.files)
    source_dirs_with_tf_files = {
        d: files
        for d, files in all_source_dirs.items()
        if any(f for f in files if f.endswith(".tf"))
    }
    if len(source_dirs_with_tf_files) == 0:
        raise ValueError("unable to determine main source directory for terrafor_module")
    elif len(source_dirs_with_tf_files) > 1:
        raise ValueError("multiple potential source dirs. ambiguous!")

    source_dir = list(source_dirs_with_tf_files.keys())[0]

    output_files = ()
    output_directories = ()
    if tf_run.options.capture_caches:
        output_files = (f"{source_dir}/.terraform.lock.hcl",)
        output_directories = (f"{source_dir}/.terraform",)

    args = (f"-chdir={source_dir}",) + tuple(tf_run.options.args)

    process = await Get(
        Process,
        TerraformProcess(
            args=args,
            description=f"Run Terraform command: {args}",
            input_digest=input_digest,
            output_files=output_files,
            output_directories=output_directories,
        ),
    )

    result = await Get(ProcessResult, Process, process)

    if tf_run.options.capture_caches:
        workspace.write_digest(result.output_digest)

    console.write_stdout(str(result.stdout))
    console.write_stderr(str(result.stderr))
    return TerraformRunGoal(exit_code=0)


def rules():
    return collect_rules()
