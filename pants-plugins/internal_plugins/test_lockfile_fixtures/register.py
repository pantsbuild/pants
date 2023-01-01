# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from internal_plugins.test_lockfile_fixtures.rules import rules as test_lockfile_fixtures_rules
from pants.backend.python.register import rules as python_rules
from pants.backend.python.register import target_types as python_target_types
from pants.core.goals.test import rules as core_test_rules
from pants.core.util_rules import config_files, source_files
from pants.jvm.resolve import coursier_fetch, coursier_setup


def target_types():
    return python_target_types()


def rules():
    return (
        *test_lockfile_fixtures_rules(),
        *python_rules(),  # python backend
        *core_test_rules(),
        *config_files.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *source_files.rules(),
    )
