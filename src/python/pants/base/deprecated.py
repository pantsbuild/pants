# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import warnings
from functools import wraps

import six

from pants.base.revision import Revision
from pants.version import VERSION


_PANTS_SEMVER = Revision.semver(VERSION)


class DeprecationApplicationError(Exception):
  """The base exception type thrown for any form of @deprecation application error."""


class MissingRemovalVersionError(DeprecationApplicationError):
  """Indicates the required removal_version was not supplied."""


class BadRemovalVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version was not a valid semver string."""


class PastRemovalVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version is not in the future.

  All deprecations must give at least until the next release for users to adapt.
  """


class BadDecoratorNestingError(DeprecationApplicationError):
  """Indicates the @deprecated decorator was innermost in a sequence of layered decorators."""


def check_deprecated_semver(removal_version):
  """Check to see if the removal version is < the current Pants version.
   :param str removal_version: The pantsbuild.pants version which will remove the deprecated
                              function.
   :raises DeprecationApplicationError if the removal_version parameter is invalid or the version
   is not an earlier version than the current release version.
  """
  if not isinstance(removal_version, six.string_types):
    raise BadRemovalVersionError('The removal_version must be a semver version string.')

  try:
    removal_semver = Revision.semver(removal_version)
  except Revision.BadRevision as e:
    raise BadRemovalVersionError('The given removal version {} is not a valid semver: '
                                 '{}'.format(removal_version, e))

  if removal_semver <= _PANTS_SEMVER:
    raise PastRemovalVersionError('The removal version must be greater than the current pants '
                                  'version of {} - given {}'.format(VERSION, removal_version))


def deprecated(removal_version, hint_message=None):
  """Marks a function or method as deprecated.

  A removal version must be supplied and it must be greater than the current 'pantsbuild.pants'
  version.

  When choosing a removal version there is a natural tension between the code-base, which benefits
  from short deprecation cycles, and the user-base which may prefer to deal with deprecations less
  frequently.  As a rule of thumb, if the hint message can fully convey corrective action
  succinctly and you judge the impact to be on the small side (effects custom tasks as opposed to
  effecting BUILD files), lean towards the next release version as the removal version; otherwise,
  consider initiating a discussion to win consensus on a reasonable removal version.

  :param str removal_version: The pantsbuild.pants version which will remove the deprecated
                              function.
  :param str hint_message: An optional hint pointing to alternatives to the deprecation.
  :raises DeprecationApplicationError if the @deprecation is applied improperly.
  """
  if removal_version is None:
    raise MissingRemovalVersionError('A removal_version must be specified for this deprecation.')

  check_deprecated_semver(removal_version)

  def decorator(func):
    if not inspect.isfunction(func):
      raise BadDecoratorNestingError('The @deprecated decorator must be applied innermost of all '
                                     'decorators.')

    warning_message = ('\n{module}.{func_name} is deprecated and will be removed in version '
                       '{removal_version}').format(module=func.__module__,
                                                   func_name=func.__name__,
                                                   removal_version=removal_version)

    if hint_message:
      warning_message += (':\n' + hint_message)
    else:
      warning_message += '.'

    @wraps(func)
    def wrapper(*args, **kwargs):
      warnings.warn(warning_message, DeprecationWarning, stacklevel=2)
      return func(*args, **kwargs)
    return wrapper
  return decorator


def deprecated_module(removal_version, hint_message=None):
  """Marks an entire module as deprecated.

  Add a call to this at the top of the deprecated module, and it will print a warning message
  when the module is imported.

  Arguments are as for deprecated(), above.
  """
  if removal_version is None:
    raise MissingRemovalVersionError('A removal_version must be specified for this deprecation.')

  check_deprecated_semver(removal_version)

  warning_message = ('\nModule is deprecated and will be removed in version '
                     '{removal_version}').format(removal_version=removal_version)

  if hint_message:
    warning_message += (': ' + hint_message)
  else:
    warning_message += '.'
  warnings.warn(warning_message, DeprecationWarning, stacklevel=2)
