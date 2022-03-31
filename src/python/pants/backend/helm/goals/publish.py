# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.core.goals.publish import (
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.backend.helm.target_types import HelmChartMetaSourceField, HelmRegistriesField, HelmSkipPushField, HelmChartRepositoryField

class PublishHelmChartRequest(PublishRequest):
  pass

@dataclass(frozen=True)
class HelmPublishFieldSet(PublishFieldSet):
  publish_request_type = PublishHelmChartRequest
  required_fields = (HelmChartMetaSourceField,)

  chart: HelmChartMetaSourceField
  registries: HelmRegistriesField
  repository: HelmChartRepositoryField
  skip_push: HelmSkipPushField

  def get_output_data(self) -> PublishOutputData:
    return PublishOutputData(
        {
            "publisher": "helm",
            "registries": self.registries.value or (),
            **super().get_output_data(),
        }
    )
