# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals.package_image import rules as package_rules
from pants.backend.docker.goals.publish import rules as publish_rules
from pants.backend.docker.goals.run_image import rules as run_rules
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.util_rules.dependencies import rules as dependencies_rules
from pants.backend.docker.util_rules.docker_binary import rules as binary_rules
from pants.backend.docker.util_rules.docker_build_args import rules as build_args_rules
from pants.backend.docker.util_rules.docker_build_context import rules as context_rules
from pants.backend.docker.util_rules.docker_build_env import rules as build_env_rules
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules


def rules():
    return [
        *binary_rules(),
        *build_args_rules(),
        *build_env_rules(),
        *context_rules(),
        *dependencies_rules(),
        *dockerfile_rules(),
        *package_rules(),
        *parser_rules(),
        *publish_rules(),
        *run_rules(),
    ]
