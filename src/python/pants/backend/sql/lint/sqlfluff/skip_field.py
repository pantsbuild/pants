# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.sql.target_types import SqlSourcesGeneratorTarget, SqlSourceTarget
from pants.engine.target import BoolField


class SkipSqlfluffField(BoolField):
    alias = "skip_sqlfluff"
    default = False
    help = "If true, don't run sqlfluff on this target's code."


def rules():
    return [
        SqlSourcesGeneratorTarget.register_plugin_field(SkipSqlfluffField),
        SqlSourceTarget.register_plugin_field(SkipSqlfluffField),
    ]
