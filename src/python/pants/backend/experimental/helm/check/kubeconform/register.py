# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.experimental.helm.register import rules as helm_rules
from pants.backend.experimental.helm.register import target_types as helm_target_types
from pants.backend.helm.check.kubeconform.chart import rules as chart_rules
from pants.backend.helm.check.kubeconform.deployment import rules as deployment_rules


def target_types():
    return helm_target_types()


def rules():
    return [*helm_rules(), *chart_rules(), *deployment_rules()]
