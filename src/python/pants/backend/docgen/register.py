# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.docgen.targets.doc import Page, Wiki, WikiArtifact
from pants.backend.docgen.tasks.confluence_publish import ConfluencePublish
from pants.backend.docgen.tasks.generate_pants_reference import GeneratePantsReference
from pants.backend.docgen.tasks.markdown_to_html import MarkdownToHtml
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'page': Page,
    },
    objects={
      # TODO: This is a Task subclass, and so should definitely not be a BUILD file object.
      # Presumably it is to allow it to be subclassed in a BUILD file, and we do NOT endorse that kind of thing.
      'ConfluencePublish': ConfluencePublish,
      'wiki_artifact': WikiArtifact,
      # TODO: Why is this capitalized?
      'Wiki': Wiki,
    },
  )


def register_goals():
  task(name='markdown', action=MarkdownToHtml).install(),
  task(name='reference', action=GeneratePantsReference).install()
