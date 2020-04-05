# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Atlassian's Confluence service.

See https://www.atlassian.com/software/confluence.
"""

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.confluence.tasks.confluence_publish import ConfluencePublish


def register_goals():
    task(name="confluence", action=ConfluencePublish).install()
