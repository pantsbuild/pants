# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.deprecated import warn_or_error
from pants.base.specs import SingleAddress, Specs
from pants.base.target_roots import TargetRoots
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.goal.workspace import ScmWorkspace
from pants.scm.subsystems.changed import ChangedRequest


logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRootsCalculator(object):
  """Determines the target roots for a given pants run."""

  @classmethod
  def parse_specs(cls, target_specs, build_root=None, exclude_patterns=None, tags=None):
    """Parse string specs into unique `Spec` objects.

    :param iterable target_specs: An iterable of string specs.
    :param string build_root: The path to the build root.
    :returns: An `OrderedSet` of `Spec` objects.
    """
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)

    dependencies = tuple(OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in target_specs))
    if not dependencies:
      return None
    return [Specs(
      dependencies=dependencies,
      exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
      tags=tags)
    ]

  @classmethod
  def changed_files(cls, scm, changes_since=None, diffspec=None):
    """Determines the files changed according to SCM/workspace and options."""
    workspace = ScmWorkspace(scm)
    if diffspec:
      return workspace.changes_in(diffspec)

    changes_since = changes_since or scm.current_rev_identifier()
    return workspace.touched_files(changes_since)

  @classmethod
  def create(cls, options, session, symbol_table, build_root=None, exclude_patterns=None, tags=None):
    """
    :param Options options: An `Options` instance to use.
    :param session: The Scheduler session
    :param symbol_table: The symbol table
    :param string build_root: The build root.
    """
    # Determine the literal target roots.
    spec_roots = cls.parse_specs(
      target_specs=options.target_specs,
      build_root=build_root,
      exclude_patterns=exclude_patterns,
      tags=tags)

    global_include_dependees = options.for_global_scope().include_dependees_behavior

    # Determine `Changed` arguments directly from options to support pre-`Subsystem`
    # initialization paths.
    changed_options = options.for_scope('changed')
    # Determine --include-dependees from the global or scoped option, for now.
    if 'include_dependees' in changed_options.get_explicit_keys():
      warn_or_error('1.17.0.dev0',
                    'The --include-dependees option in the Changed subsystem.',
                    'Use the --include-dependees-behavior global option instead!')
      include_dependees = changed_options.include_dependees
    else:
      include_dependees = global_include_dependees

    changed_request = ChangedRequest.from_options(
      changed_options,
      include_dependees=include_dependees)

    # Determine the `--owner-of=` arguments provided from the global options
    owned_files = options.for_global_scope().owner_of

    logger.debug('spec_roots are: %s', spec_roots)
    logger.debug('changed_request is: %s', changed_request)
    logger.debug('owned_files are: %s', owned_files)
    targets_specified = sum(1 for item
                         in (changed_request.is_actionable(), owned_files, spec_roots)
                         if item)

    if targets_specified > 1:
      # We've been provided more than one of: a change request, an owner request, or spec roots.
      raise InvalidSpecConstraint(
        'Multiple target selection methods provided. Please use only one of '
        '--changed-*, --owner-of, or target specs'
      )

    if changed_request.is_actionable():
      scm = get_scm()
      if not scm:
        raise InvalidSpecConstraint(
          'The --changed-* options are not available without a recognized SCM (usually git).'
        )
      changed_files = cls.changed_files(
          scm,
          changes_since=changed_request.changes_since,
          diffspec=changed_request.diffspec)
      # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
      # alternate target roots.
      request = OwnersRequest(sources=tuple(changed_files),
                              include_dependees=changed_request.include_dependees)
      changed_addresses, = session.product_request(BuildFileAddresses, [request])
      logger.debug('changed addresses: %s', changed_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in changed_addresses)
      return TargetRoots([Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags)])

    if owned_files:
      # We've been provided no spec roots (e.g. `./pants list`) AND a owner request. Compute
      # alternate target roots.
      request = OwnersRequest(sources=tuple(owned_files), include_dependees=global_include_dependees)
      owner_addresses, = session.product_request(BuildFileAddresses, [request])
      logger.debug('owner addresses: %s', owner_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in owner_addresses)
      return TargetRoots([Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags)])

    return TargetRoots(spec_roots)
