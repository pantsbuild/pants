# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.lang import Compatibility

from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.payload import SourcesPayload, hash_sources
from pants.base.target import Target


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


class Wiki(Target):
  """Target that identifies a wiki where pages can be published."""

  def __init__(self, name, url_builder, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param url_builder: Function that accepts a page target and an optional wiki config dict.
    :returns: A tuple of (alias, fully qualified url).
    """
    super(Wiki, self).__init__(name, **kwargs)
    self.url_builder = url_builder


class Page(Target):
  """Describes a single documentation page.

  Here is an example, that shows a markdown page providing a wiki page on an Atlassian Confluence
  wiki: ::

     page(name='mypage',
       source='mypage.md',
       provides=[
         wiki_artifact(wiki='address/of/my/wiki/target',
                       space='my_space',
                       title='my_page',
                       parent='my_parent'),
       ],
     )

  A ``page`` can have more than one ``wiki_artifact`` in its ``provides``
  (there might be more than one place to publish it).
  """

  class PagePayload(SourcesPayload):
    def __init__(self, sources_rel_path, source, resources=None, provides=None):
      super(Page.PagePayload, self).__init__(sources_rel_path, [source])
      self.resources = list(resources or [])
      self.provides = list(provides or [])

    def invalidation_hash(self):
      return hash_sources(get_buildroot(), self.sources_rel_path, self.sources)


  def __init__(self, source, resources=None, provides=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param source: Source of the page in markdown format.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param resources: An optional list of Resources objects.
    """

    payload = self.PagePayload(sources_rel_path=kwargs.get('address').spec_path,
                               source=source,
                               resources=resources,
                               provides=provides)
    super(Page, self).__init__(payload=payload, **kwargs)

    if provides and len(provides)>0 and not isinstance(provides[0], WikiArtifact):
      raise ValueError('Page must provide a wiki_artifact. Found instead: %s' % provides)

  @property
  def source(self):
    return list(self.payload.sources)[0]

  # This callback needs to yield every 'pants(...)' pointer that we need to have resolved into the
  # build graph. This includes wiki objects in the provided WikiArtifact objects, and any 'pants()'
  # pointers inside of the documents themselves (yes, this can happen).
  @property
  def traversable_specs(self):
    if self.payload.provides:
      for wiki_artifact in self.payload.provides:
        yield wiki_artifact.wiki

  # This callback is used to link up the provided WikiArtifact objects to Wiki objects. In the build
  # file, a 'pants(...)' pointer is specified to the Wiki object. In this method, this string
  # pointer is resolved in the build graph, and an actual Wiki object is swapped in place of the
  # string.
  @property
  def provides(self):
    if not self.payload.provides:
      return None

    for p in self.payload.provides:
      if isinstance(p.wiki, Wiki):
        # We have already resolved this string into an object, so skip it.
        continue
      if isinstance(p.wiki, Compatibility.string):
        address = SyntheticAddress.parse(p.wiki, relative_to=self.address.spec_path)
        repo_target = self._build_graph.get_target(address)
        p.wiki = repo_target
      else:
        raise ValueError('A WikiArtifact must depend on a string pointer to a Wiki. Found %s instead.'
                         % p.wiki)
    return self.payload.provides
