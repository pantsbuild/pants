# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.confluence.targets.doc_page import Page, WikiArtifact, Wiki
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'page': Page,
    },
    objects={
      'wiki_artifact': WikiArtifact,
      'wiki': Wiki,
    },
  )


def register_goals():
  task(name='confluence', action=ConfluencePublish).install()
