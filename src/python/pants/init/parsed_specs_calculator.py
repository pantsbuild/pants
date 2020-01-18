# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Iterable, Optional

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import (
  AddressSpec,
  AddressSpecs,
  FilesystemSpec,
  FilesystemSpecs,
  ParsedSpecs,
  SingleAddress,
)
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.engine.scheduler import SchedulerSession
from pants.goal.workspace import ScmWorkspace
from pants.option.options import Options
from pants.scm.subsystems.changed import ChangedRequest


logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via specs and arguments like --changed*."""


class ParsedSpecsCalculator:
  """Determines the parsed specs for a given Pants run."""

  @classmethod
  def parse_specs(
    cls,
    raw_specs: Iterable[str],
    build_root: Optional[str] = None,
    exclude_patterns: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
  ) -> ParsedSpecs:
    """Parse string specs into a ParsedSpecs object."""
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)
    parsed_specs = OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in raw_specs)
    address_specs = AddressSpecs(
      dependencies=(spec for spec in parsed_specs if isinstance(spec, AddressSpec)),
      exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
      tags=tags,
    )
    filesystem_specs = FilesystemSpecs(
      spec for spec in parsed_specs if isinstance(spec, FilesystemSpec)
    )
    return ParsedSpecs(address_specs=address_specs, filesystem_specs=filesystem_specs)

  @classmethod
  def changed_files(cls, scm, changes_since=None, diffspec=None):
    """Determines the files changed according to SCM/workspace and options."""
    workspace = ScmWorkspace(scm)
    if diffspec:
      return workspace.changes_in(diffspec)

    changes_since = changes_since or scm.current_rev_identifier()
    return workspace.touched_files(changes_since)

  @classmethod
  def create(
    cls,
    options: Options,
    session: SchedulerSession,
    build_root: Optional[str] = None,
    exclude_patterns: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
  ) -> ParsedSpecs:
    # Determine the literal specs.
    parsed_specs = cls.parse_specs(
      raw_specs=options.specs,
      build_root=build_root,
      exclude_patterns=exclude_patterns,
      tags=tags,
    )

    # Determine `Changed` arguments directly from options to support pre-`Subsystem`
    # initialization paths.
    changed_options = options.for_scope('changed')
    changed_request = ChangedRequest.from_options(changed_options)

    # Determine the `--owner-of=` arguments provided from the global options
    owned_files = options.for_global_scope().owner_of

    logger.debug('parsed_specs are: %s', parsed_specs)
    logger.debug('changed_request is: %s', changed_request)
    logger.debug('owned_files are: %s', owned_files)
    targets_specified = sum(
      1 for item
      in (changed_request.is_actionable(), owned_files, parsed_specs.provided_specs.dependencies)
      if item
    )

    if targets_specified > 1:
      # We've been provided more than one of: a change request, an owner request, or specs.
      raise InvalidSpecConstraint(
        'Multiple target selection methods provided. Please use only one of '
        '--changed-*, --owner-of, address specs, or filesystem specs.'
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
      return ParsedSpecs(
        address_specs=AddressSpecs(
          dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags,
        ),
        filesystem_specs=FilesystemSpecs([]),
      )

    if owned_files:
      # We've been provided no spec roots (e.g. `./pants list`) AND a owner request. Compute
      # alternate target roots.
      request = OwnersRequest(sources=tuple(owned_files), include_dependees='none')
      owner_addresses, = session.product_request(BuildFileAddresses, [request])
      logger.debug('owner addresses: %s', owner_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in owner_addresses)
      return ParsedSpecs(
        address_specs=AddressSpecs(
          dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags,
        ),
        filesystem_specs=FilesystemSpecs([])
      )

    return parsed_specs
