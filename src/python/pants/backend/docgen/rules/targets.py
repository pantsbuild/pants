# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Optional, Tuple

from pants.backend.docgen.targets.doc import WikiArtifact
from pants.build_graph.address import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    SequenceField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)


class PageSources(Sources):
    """Exactly one Markdown (.md) or RST (.rst) file."""

    required = True
    expected_file_extensions = (".md", ".rst")
    expected_num_files = 1


class PageSourcesFormat(StringField):
    """The file format for the page.

    This will be inferred from the source file if not explicitly specified.
    """

    alias = "format"
    valid_choices = ("md", "rst")


class PageLinks(StringSequenceField):
    """Addresses to other `page` targets that this `page` links to."""

    alias = "links"


# TODO: This should probably subclass `ProvidesField` so that `list --provides` will include the
#  value. But, it looks like V1 doesn't do this and `list` wouldn't know how to handle this being
#  a sequence.
class PageProvides(SequenceField):
    """Wiki locations at which to publish the page."""

    expected_element_type = WikiArtifact
    expected_type_description = "an iterable of `wiki_artifact` objects (e.g. a list)"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[WikiArtifact]], *, address: Address
    ) -> Optional[Tuple[WikiArtifact, ...]]:
        return super().compute_value(raw_value, address=address)


class Page(Target):
    """A documentation page.

    Here is an example, which shows a markdown page providing a wiki page on an Atlassian Confluence
    Wiki:

        page(
            name='home_page',
            source='home_page.md',
            provides=[
                wiki_artifact(
                    wiki=Wiki('foozle', <url builder>),
                    space='my_space',
                    title='my_page',
                    parent='my_parent',
                ),
            ],
       )
    """

    alias = "page"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PageSources, PageSourcesFormat, PageLinks)
    v1_only = True
