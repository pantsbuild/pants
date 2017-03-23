# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import SingleAddress
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.subsystems.changed import ChangedRequest


logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRoots(object):
  """Determines the target roots for a given pants run."""

  @classmethod
  def parse_specs(cls, target_specs, build_root=None):
    """Parse string specs into unique `Spec` objects.

    :param iterable target_specs: An iterable of string specs.
    :param string build_root: The path to the build root.
    :returns: An `OrderedSet` of `Spec` objects.
    """
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)
    return OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in target_specs)

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
    spec_roots = cls.parse_specs(options.target_specs, build_root)

    # Determine `Changed` arguments directly from options to support pre-`Subsystem`
    # initialization paths.
    changed_options = options.for_scope('changed')
    changed_request = ChangedRequest.from_options(changed_options)

    logger.debug('args are: %s', args)
    logger.debug('spec_roots are: %s', spec_roots)
    logger.debug('changed_request is: %s', changed_request)

    if change_calculator and changed_request.is_actionable():
      if spec_roots:
        # We've been provided spec roots (e.g. `./pants list ::`) AND a changed request. Error out.
        raise InvalidSpecConstraint('cannot provide changed parameters and target specs!')

      # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
      # alternate target roots.
      changed_addresses = change_calculator.changed_target_addresses(changed_request)
      logger.debug('changed addresses: %s', changed_addresses)
      return ChangedTargetRoots(tuple(SingleAddress(a.spec_path, a.target_name)
                                      for a in changed_addresses))

    return LiteralTargetRoots(spec_roots)

  def __init__(self, spec_roots):
    self._spec_roots = spec_roots

  def as_specs(self):
    """Returns the current target roots as Specs."""
    return self._spec_roots

  def __repr__(self):
    return '{}({!r})'.format(self.__class__.__name__, self.as_specs())


class ChangedTargetRoots(TargetRoots):
  """Target roots that have been altered by `--changed` functionality."""


class LiteralTargetRoots(TargetRoots):
  """User defined target roots."""
