# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.base.target import Target


class Wiki(Target):
  """Target that identifies a wiki where pages can be published."""

  def __init__(self, name, url_builder, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param url_builder: Function that accepts a page target and an optional wiki config dict.
    :returns: A tuple of (alias, fully qualified url).
    """
    Target.__init__(self, name, exclusives=exclusives)
    self.url_builder = url_builder


class Page(Target):
  """Describes a single documentation page."""

  def __init__(self, resources=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param source: Source of the page in markdown format.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param resources: An optional list of Resources objects.
    """

    payload = None
    super(Page, self).__init__(**kwargs)

    self.resources = self._resolve_paths(resources) if resources else []
    self._wikis = {}

  @property
  def source(self):
    return self.sources[0]

  @manual.builddict()
  def register_wiki(self, wiki, **kwargs):
    """Adds this page to the given wiki for publishing.  Wiki-specific configuration is passed as
    kwargs.
    """
    if isinstance(wiki, Pants):
      wiki = wiki.get()
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
