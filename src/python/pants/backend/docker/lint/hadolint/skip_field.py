# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.target_types import DockerImageTarget
from pants.engine.target import BoolField


class SkipHadolintField(BoolField):
    alias = "skip_hadolint"
    default = False
    help = "If true, don't run hadolint on this target's Dockerfile."


def rules():
    return [DockerImageTarget.register_plugin_field(SkipHadolintField)]
