# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.hash_utils import stable_json_hash
from pants.base.payload import Payload
from pants.base.payload_field import PayloadField, PrimitiveField, combine_hashes
from pants.build_graph.target import Target


class WikiArtifact(object):
  """Binds a single documentation page to a wiki instance.

  This object allows you to specify which wiki a page should be published to, along with additional
  wiki-specific parameters, such as the title, parent page, etc.
  """

  def __init__(self, wiki, **kwargs):
    """
    :param wiki: target spec of a ``wiki``.
    :param kwargs: a dictionary that may contain configuration directives for your particular wiki.
      For example, the following keys are supported for Atlassian's Confluence:

      * ``space`` -- A wiki space in which to place the page (used in Confluence)
      * ``title`` -- A title for the wiki page
      * ``parent`` -- The title of a wiki page that will denote this page as a child.
    """
    self.wiki = wiki
    self.config = kwargs

  def fingerprint(self):
    return combine_hashes([self.wiki.fingerprint(), stable_json_hash(self.config)])

  def __str__(self):
    return self.wiki.name


class Wiki(object):
  """Identifies a wiki where pages can be published."""

  def __init__(self, name, url_builder):
    """
    :param url_builder: Function that accepts a page target and an optional wiki config dict.
    """
    self.name = name
    self.url_builder = url_builder

  def fingerprint(self):
    # TODO: url_builder is not a part of fingerprint.
    return stable_json_hash(self.name)


class Page(Target):
  """A documentation page.

  Here is an example, that shows a markdown page providing a wiki page on an Atlassian Confluence
  wiki: ::

     page(name='mypage',
       source='mypage.md',
       provides=[
         wiki_artifact(wiki=Wiki('foozle', <url builder>),
                       space='my_space',
                       title='my_page',
                       parent='my_parent'),
       ],
     )

  A ``page`` can have more than one ``wiki_artifact`` in its ``provides``
  (there might be more than one place to publish it).
  """

  class ProvidesTupleField(tuple, PayloadField):
    def _compute_fingerprint(self):
      return combine_hashes(artifact.fingerprint() for artifact in self)

  def __init__(self,
               address=None,
               payload=None,
               source=None,
               format=None,
               links=None,
               provides=None,
               **kwargs):
    """
    :param source: Path to page source file.
    :param format: Page's format, ``md`` or ``rst``. By default, Pants infers from ``source`` file
       extension: ``.rst`` is ReStructured Text; anything else is Markdown.
    :param links: Other ``page`` targets that this `page` links to.
    :type links: List of target specs
    :param provides: Optional "Addresses" at which this page is published.
       E.g., a wiki location.
    :type provides: List of ``wiki_artifact``s
    """
    payload = payload or Payload()
    if not format:
      if source and source.lower().endswith('.rst'):
        format = 'rst'
      else:
        format = 'md'
    payload.add_fields({
      'sources': self.create_sources_field(sources=[source],
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
      'format': PrimitiveField(format),
      'links': PrimitiveField(links or []),
      'provides': self.ProvidesTupleField(provides or []),
    })
    super(Page, self).__init__(address=address, payload=payload, **kwargs)

    if provides and not isinstance(provides[0], WikiArtifact):
      raise ValueError('Page must provide a wiki_artifact. Found instead: {}'.format(provides))

  @property
  def source(self):
    """The first (and only) source listed by this Page."""
    return list(self.payload.sources.source_paths)[0]

  @classmethod
  def compute_injectable_specs(cls, kwargs=None, payload=None):
    for spec in super(Page, cls).compute_injectable_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    for spec in target_representation.get('links', []):
      yield spec

  @property
  def provides(self):
    """A tuple of WikiArtifact instances provided by this Page.

    Notably different from JvmTarget.provides, which has only a single Artifact rather than a
    list.
    """
    return self.payload.provides

  @property
  def format(self):
    """Returns this page's format, 'md' (Markdown) or 'rst' (ReStructured Text)."""
    return self.payload.format
