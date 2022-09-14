# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.environments import DockerPlatformField, EnvironmentTarget
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule


@rule
def current_platform(env_tgt: EnvironmentTarget) -> Platform:
    if env_tgt.val is None or not env_tgt.val.has_field(DockerPlatformField):
        return Platform.create_for_localhost()
    return Platform(env_tgt.val[DockerPlatformField].value)


def rules():
    return collect_rules()
