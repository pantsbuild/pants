# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase


class Redocly(NodeJSToolBase):
    options_scope = "redocly"
    name = "redocly"
    help = "Redocly CLI toolbox with rich validation and bundling features (https://github.com/Redocly/redocly-cli)."

    default_version = "@redocly/cli@1.10.5"
