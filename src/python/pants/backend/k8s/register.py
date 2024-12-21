from experimental.k8s import k8s_subsystem, kubectl_subsystem, targets
from experimental.k8s.goals import deploy


def rules():
    return [
        *kubectl_subsystem.rules(),
        *k8s_subsystem.rules(),
        *deploy.rules(),
    ]


def target_types():
    return [*targets.target_types()]
