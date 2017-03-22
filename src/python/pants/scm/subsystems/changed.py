# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_environment import get_scm
from pants.base.exceptions import TaskError
from pants.goal.workspace import ScmWorkspace
from pants.scm.change_calculator import BuildGraphChangeCalculator
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype


# TODO: Remove this in 1.5.0dev0.
class _ChainedOptions(object):
  def __init__(self, options_seq):
    self._options_seq = options_seq

  def __getattr__(self, attr):
    for options in self._options_seq:
      option_value = getattr(options, attr, None)
      if option_value is not None:
        return option_value
    return None


class ChangedRequest(datatype('ChangedRequest',
                              ['changes_since', 'diffspec', 'include_dependees', 'fast'])):
  """Parameters required to compute a changed file/target set."""

  @classmethod
  def from_options(cls, options):
    """Given an `Options` object, produce a `ChangedRequest`."""
    return cls(options.changes_since,
               options.diffspec,
               options.include_dependees,
               options.fast)

  def is_actionable(self):
    return bool(self.changes_since or self.diffspec)


class Changed(object):
  """A subsystem for global `changed` functionality.

  This supports the "legacy" `changed`, `test-changed` and `compile-changed` goals as well as the
  v2 engine style `--changed-*` argument target root replacements which can apply to any goal (e.g.
  `./pants --changed-parent=HEAD~3 list` replaces `./pants --changed-parent=HEAD~3 changed`).
  """

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

    # TODO: Remove or reduce this in 1.5.0dev0 - we only need the subsystem's options scope going fwd.
    @classmethod
    def create(cls, alternate_options=None):
      """
      :param Options alternate_options: An alternate `Options` object for overrides.
      """
      options = cls.global_instance().get_options()
      # N.B. This chaining is purely to support the `changed` tests until deprecation.
      ordered_options = [option for option in (alternate_options, options) if option is not None]
      # TODO: Kill this chaining (in favor of outright options replacement) as part of the `changed`
      # task removal (post-deprecation cycle). See https://github.com/pantsbuild/pants/issues/3893
      chained_options = _ChainedOptions(ordered_options)
      changed_request = ChangedRequest.from_options(chained_options)
      return Changed(changed_request)

  def __init__(self, changed_request):
    self._changed_request = changed_request

  # TODO: Remove this in 1.5.0dev0 in favor of `TargetRoots` use of `EngineChangeCalculator`.
  def change_calculator(self, build_graph, address_mapper, scm=None, workspace=None,
                        exclude_target_regexp=None):
    """Constructs and returns a BuildGraphChangeCalculator.

    :param BuildGraph build_graph: A BuildGraph instance.
    :param AddressMapper address_mapper: A AddressMapper instance.
    :param Scm scm: The SCM instance. Defaults to discovery.
    :param ScmWorkspace: The SCM workspace instance.
    :param string exclude_target_regexp: The exclude target regexp.
    """
    scm = scm or get_scm()
    if scm is None:
      raise TaskError('A `changed` goal or `--changed` option was specified, '
                      'but no SCM is available to satisfy the request.')
    workspace = workspace or ScmWorkspace(scm)

    return BuildGraphChangeCalculator(
      scm,
      workspace,
      address_mapper,
      build_graph,
      self._changed_request.include_dependees,
      fast=self._changed_request.fast,
      changes_since=self._changed_request.changes_since,
      diffspec=self._changed_request.diffspec,
      exclude_target_regexp=exclude_target_regexp
    )
