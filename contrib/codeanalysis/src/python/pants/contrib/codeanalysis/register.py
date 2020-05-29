# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for the Kythe ecosystem.

See https://www.kythe.io.
"""

from pants.base.deprecated import warn_or_error
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.codeanalysis.tasks.bundle_entries import BundleEntries
from pants.contrib.codeanalysis.tasks.extract_java import ExtractJava
from pants.contrib.codeanalysis.tasks.index_java import IndexJava

warn_or_error(
    removal_version="1.30.0.dev0",
    deprecated_entity_description="The `pants.contrib.codeanalysis` plugin",
    hint=(
        "The `pants.contrib.codeanalysis` plugin is being removed due to low usage.\n\nIf you "
        "still need this plugin, please message us on Slack (see "
        "https://pants.readme.io/docs/community)."
    ),
)


def register_goals():
    task(name="kythe-java-extract", action=ExtractJava).install("index")
    task(name="kythe-java-index", action=IndexJava).install("index")
    task(name="bundle-entries", action=BundleEntries).install("index")
