# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.goals import install, lint, package, publish, tailor
from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.target_types import (
    HelmArtifactTarget,
    HelmChartTarget,
    HelmDeploymentTarget,
)
from pants.backend.helm.util_rules import chart, deployment, render, sources, tool


def target_types():
    return [HelmChartTarget, HelmDeploymentTarget, HelmArtifactTarget]


def rules():
    return [
        *artifacts.rules(),
        *tool.rules(),
        *chart.rules(),
        *deployment.rules(),
        *fetch.rules(),
        *lint.rules(),
        *package.rules(),
        *render.rules(),
        *tailor.rules(),
        *sources.rules(),
        *publish.rules(),
        *install.rules(),
    ]
