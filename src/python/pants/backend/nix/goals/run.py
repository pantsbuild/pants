import os

from pants.backend.nix.target_types import NixBinaryExprField, NixBinaryRelativePathField
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.system_binaries import SystemBinariesSubsystem
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import WrappedTarget, WrappedTargetRequest


class NixBinaryFieldSet(RunFieldSet):
    required_fields = (
        NixBinaryExprField,
        NixBinaryRelativePathField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC


@rule
async def run_nix_binary(
    field_set: NixBinaryFieldSet,
    system_binaries: SystemBinariesSubsystem.EnvironmentAware,
) -> RunRequest:
    wrapped_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
    )
    expr = wrapped_tgt.target[NixBinaryExprField].value
    assert expr
    rel_path = wrapped_tgt.target[NixBinaryRelativePathField].value
    assert rel_path

    # TODO search path
    nix_instantiate = "/nix/var/nix/profiles/default/bin/nix-instantiate"
    instantiate_result = await Get(
        ProcessResult,
        Process(
            argv=(nix_instantiate, "--expr", expr),
            description="Create nix .drv file",
        ),
    )
    drv_path = instantiate_result.stdout.decode("utf-8").strip()

    # TODO search path
    nix_store = "/nix/var/nix/profiles/default/bin/nix-store"
    realise_result = await Get(
        ProcessResult,
        Process(
            argv=(nix_store, "--realise", drv_path),
            description="Build nix derivation",
        ),
    )
    derivation_dir = realise_result.stdout.decode("utf-8").strip()

    binary_path = os.path.join(derivation_dir, rel_path)
    return RunRequest(args=[binary_path], digest=EMPTY_DIGEST)


def rules():
    return [
        *collect_rules(),
        *NixBinaryFieldSet.rules(),
    ]
