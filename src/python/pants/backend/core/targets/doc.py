# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
from pants.base.build_environment import get_buildroot

from pants.base.build_manual import manual
from pants.base.payload import SourcesMixin, Payload, hash_sources
from pants.base.target import Target


class Wiki(Target):
  """Target that identifies a wiki where pages can be published."""

  def __init__(self, url_builder, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param url_builder: Function that accepts a page target and an optional wiki config dict.
    :returns: A tuple of (alias, fully qualified url).
    """
    super(Wiki, self).__init__(**kwargs)
    self.url_builder = url_builder


class Page(Target):
  """Describes a single documentation page."""

  class PagePayload(SourcesMixin, Payload):
    def __init__(self, source_rel_path, source, resources=None):
      self.sources_rel_path = source_rel_path
      self.sources = [source]
      self.resources = list(resources or [])

    def invalidation_hash(self):
      return hash_sources(get_buildroot(), self.sources_rel_path, self.sources)

  def __init__(self, source, resources=None, address=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param source: Source of the page in markdown format.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param resources: An optional list of Resources objects.
    """
    payload = self.PagePayload(source_rel_path=address.spec_path,
                               source=source,
                               resources=resources)
    super(Page, self).__init__(address=address, payload=payload, **kwargs)

    self.resources = self._resolve_paths(resources) if resources else []
    self._wikis = {}

  @property
  def source(self):
    return self.payload.sources[0]

  # TODO(John Sirois): This is broken - move to a constructor parameter
  @manual.builddict()
  def register_wiki(self, wiki, **kwargs):
    """Adds this page to the given wiki for publishing.  Wiki-specific configuration is passed as
    kwargs.
    """
    if not isinstance(wiki, Wiki):
      raise ValueError('The 1st argument must be a wiki target, given: %s' % wiki)
    self._wikis[wiki] = kwargs
    return self

  def wiki_config(self, wiki):
    """Gets the wiki specific config for the given wiki if present or else returns None."""
    return self._wikis.get(wiki)

  def wikis(self):
    """Returns all the wikis registered with this page."""
    return self._wikis.keys()
