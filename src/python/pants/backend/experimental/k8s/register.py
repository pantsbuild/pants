# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.k8s import k8s_subsystem, kubectl_subsystem, targets
from pants.backend.k8s.goals import deploy


def rules():
    return [
        *kubectl_subsystem.rules(),
        *k8s_subsystem.rules(),
        *deploy.rules(),
    ]


def target_types():
    return [*targets.target_types()]
