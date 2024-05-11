# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.sql import tailor
from pants.backend.sql.target_types import SqlSourcesGeneratorTarget, SqlSourceTarget


def target_types():
    return [
        SqlSourceTarget,
        SqlSourcesGeneratorTarget,
    ]


def rules():
    return [*tailor.rules()]
