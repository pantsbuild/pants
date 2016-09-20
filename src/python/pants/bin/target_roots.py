# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import DescendantAddresses, Spec
from pants.bin.options_initializer import OptionsInitializer
from pants.build_graph.address import Address
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.subsystems.changed import ChangedRequest


logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRoots(object):
  """Determines the target roots for a given pants run."""

  @classmethod
  def create(cls, options=None, args=None, build_root=None, change_calculator=None):
    """
    :param Options options: An `Options` instance to use, if available.
    :param string args: Raw cli args to use for parsing if an `Options` instance isn't available.
    :param string build_root: The build root.
    :param ChangeCalculator change_calculator: A `ChangeCalculator` for calculating changes.
    """
    if not options:
      assert args is not None, 'must pass `args` if not passing `options`'
      options, _ = OptionsInitializer(OptionsBootstrapper(args=args)).setup(init_logging=False)

    # Determine the literal target roots.
    cmd_line_spec_parser = CmdLineSpecParser(build_root or get_buildroot())
    spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in options.target_specs]

    # Determine `Changed` arguments directly from options to support pre-`Subsystem` initialization paths.
    changed_options = options.for_scope('changed')
    changed_request = ChangedRequest.from_options(changed_options)

    logger.debug('args are: %s', args)
    logger.debug('spec_roots are: %s', spec_roots)
    logger.debug('changed_request is: %s', changed_request)

    if change_calculator and changed_request and changed_request.is_actionable():
      if spec_roots:
        # We've been provided spec roots (e.g. `./pants list ::`) AND a changed request. Error out.
        raise InvalidSpecConstraint('cannot provide changed parameters and target specs!')

      # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
      # alternate target roots.
      changed_addresses = change_calculator.changed_target_addresses(changed_request)
      logger.debug('changed addresses: %s', changed_addresses)
      return ChangedTargetRoots(changed_addresses)

    # If no spec roots are passed, assume `::` as the intended target.
    return LiteralTargetRoots(spec_roots if spec_roots else [DescendantAddresses('')])

  def __init__(self, spec_roots):
    self._spec_roots = spec_roots

  def as_string_specs(self):
    """Returns the current target roots as stringified specs for v1 compatibility."""
    # TODO: Kill this once `LegacyAddressMapper.specs_to_addresses()` exists.

    def _to_addresses(spec_roots):
      for spec in spec_roots:
        if isinstance(spec, Spec):
          yield spec.to_spec_string()
        elif isinstance(spec, Address):
          yield spec.spec
        else:
          raise TypeError('unsupported spec type `{}` when converting {!r} to string spec'
                          .format(type(spec), spec))

    return [address for address in _to_addresses(self._spec_roots)]

  def as_specs(self):
    """Returns the current target roots as Specs."""
    return self._spec_roots

  def __repr__(self):
    return '{}({!r})'.format(self.__class__.__name__, self.as_specs())


class ChangedTargetRoots(TargetRoots):
  """Target roots that have been altered by `--changed` functionality."""


class LiteralTargetRoots(TargetRoots):
  """User defined target roots."""
