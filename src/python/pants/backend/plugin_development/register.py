# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.plugin_development import pants_requirements
from pants.backend.plugin_development.goals import check_names
from pants.backend.plugin_development.pants_requirements import PantsRequirementsTargetGenerator


def rules():
    return (
        *check_names.rules(),
        *pants_requirements.rules(),
    )


def target_types():
    return [PantsRequirementsTargetGenerator]
