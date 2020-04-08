# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for generating wiki-style documentation from Markdown and RST."""

from pants.backend.docgen.rules.targets import Page
from pants.backend.docgen.targets.doc import Page as PageV1
from pants.backend.docgen.targets.doc import Wiki, WikiArtifact
from pants.backend.docgen.tasks.generate_pants_reference import GeneratePantsReference
from pants.backend.docgen.tasks.markdown_to_html import MarkdownToHtml
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(
        targets={"page": PageV1},
        objects={
            "wiki_artifact": WikiArtifact,
            # TODO: Why is this capitalized?
            "Wiki": Wiki,
        },
    )


def register_goals():
    task(name="markdown", action=MarkdownToHtml).install(),
    task(name="reference", action=GeneratePantsReference).install()


def targets2():
    return [Page]
