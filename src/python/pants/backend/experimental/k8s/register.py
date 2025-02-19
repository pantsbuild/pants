# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.k8s import k8s_subsystem, kubectl_subsystem
from pants.backend.k8s import target_types as k8s_target_types
from pants.backend.k8s.goals import deploy


def rules():
    return [
        *deploy.rules(),
        *k8s_subsystem.rules(),
        *kubectl_subsystem.rules(),
    ]


def target_types():
    return k8s_target_types.target_types()
