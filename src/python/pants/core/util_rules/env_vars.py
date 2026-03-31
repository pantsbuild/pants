# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import collect_rules, rule


@rule
async def environment_vars_subset(
    request: EnvironmentVarsRequest,
    complete_env_vars: CompleteEnvironmentVars,
) -> EnvironmentVars:
    return EnvironmentVars(
        complete_env_vars.get_subset(
            requested=tuple(request.requested),
            allowed=(None if request.allowed is None else tuple(request.allowed)),
        ).items()
    )


def rules():
    return collect_rules()
