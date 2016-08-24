# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.base.build_environment import get_scm
from pants.base.exceptions import TaskError
from pants.goal.workspace import ScmWorkspace
from pants.scm.change_calculator import BuildGraphChangeCalculator
from pants.subsystem.subsystem import Subsystem


class ChangedRequest(namedtuple('ChangedRequest', ['changes_since', 'diffspec', 'include_dependees',
                                                   'fast'])):
  """Parameters required to compute a changed file/target set."""

  @classmethod
  def from_options(cls, options):
    """Given options, produce a ChangedRequest or None if no core params are provided."""
    return cls(options.changes_since,
               options.diffspec,
               options.include_dependees,
               options.fast)

  def is_actionable(self):
    return bool(self.changes_since or self.diffspec)


class Changed(object):
  """A subsystem for global `changed` functionality."""

  class Factory(Subsystem):
    options_scope = 'changed'

    @classmethod
    def register_options(cls, register):
      register('--changes-since', '--parent', '--since',
               help='Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).')
      register('--diffspec',
               help='Calculate changes contained within given scm spec (commit range/sha/ref/etc).')
      register('--include-dependees', choices=['none', 'direct', 'transitive'], default='none',
               help='Include direct or transitive dependees of changed targets.')
      register('--fast', type=bool,
               help='Stop searching for owners once a source is mapped to at least one owning target.')

    def create(self):
      options = self.global_instance().get_options()
      changed_request = ChangedRequest.from_options(options)
      return Changed(changed_request)

  def __init__(self, changed_request):
    self._changed_request = changed_request

  @property
  def changed_request(self):
    return self._changed_request

  def change_calculator(self, config, build_graph, address_mapper, scm=None, workspace=None,
                        exclude_target_regexp=None):
    """Constructs and returns a BuildGraphChangeCalculator.

    :param object config: An object representing the options/ChangedRequest config.
    :param BuildGraph build_graph: A BuildGraph instance.
    :param AddressMapper address_mapper: A AddressMapper instance.
    :param Scm scm: The SCM instance. Defaults to discovery.
    :param ScmWorkspace: The SCM workspace instance.
    :param string exclude_target_regexp: The exclude target regexp.
    """
    scm = scm or get_scm()
    if scm is None:
      raise TaskError('No SCM available.')
    workspace = workspace or ScmWorkspace(scm)

    return BuildGraphChangeCalculator(
      scm,
      workspace,
      address_mapper,
      build_graph,
      config.include_dependees,
      fast=config.fast,
      changes_since=config.changes_since,
      diffspec=config.diffspec,
      exclude_target_regexp=exclude_target_regexp
    )
