# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.tools.remote_cache_logger import rules as remote_cache_logger_rules


def rules():
    return remote_cache_logger_rules.rules()
