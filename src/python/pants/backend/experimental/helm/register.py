# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.target_types import HelmChartTarget

def target_types():
  return [HelmChartTarget]

def rules():
  return []