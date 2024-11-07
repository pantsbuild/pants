# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.tools.trivy.rules import rules as trivy_rules
from pants.backend.docker.lint.trivy.rules import rules as trivy_docker_rules

def rules():
    return (
        *docker_rules(),
        *trivy_rules(),
        *trivy_docker_rules(),
    )
