# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.goals import lint, package
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.util_rules import chart, sources, tool


def target_types():
    return [HelmChartTarget]


def rules():
    return [*chart.rules(), *lint.rules(), *package.rules(), *sources.rules(), *tool.rules()]
