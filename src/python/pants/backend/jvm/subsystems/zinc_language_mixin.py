# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class ZincLanguageMixin(object):
  """A mixin for subsystems for languages compiled with Zinc."""

  @classmethod
  def register_options(cls, register):
    super(ZincLanguageMixin, cls).register_options(register)
    # NB: This option is fingerprinted because the default value is not included in a target's
    # fingerprint. This also has the effect of invalidating only the relevant tasks: ZincCompile
    # in this case.
    register('--strict-deps', advanced=True, default=False, fingerprint=True, action='store_true',
             help='The default for the "strict_deps" argument for targets of this language.')

    register('--fatal-warnings', advanced=True, action='store_true', default=False,
             fingerprint=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')

  @property
  def strict_deps(self):
    """When True, limits compile time deps to those that are directly declared by a target.
    :rtype: bool
    """
    return self.get_options().strict_deps

  @property
  def fatal_warnings(self):
    """If true, make warnings fatal for targets that do not specify fatal_warnings.
    :rtype: bool
    """
    return self.get_options().fatal_warnings
