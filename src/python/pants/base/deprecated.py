# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import inspect
import sys
import warnings
from functools import wraps

import six
from future.utils import PY2
from packaging.version import InvalidVersion, Version

from pants.util.memo import memoized_method
from pants.version import PANTS_SEMVER


class DeprecationApplicationError(Exception):
  """The base exception type thrown for any form of @deprecation application error."""


class MissingRemovalVersionError(DeprecationApplicationError):
  """Indicates the required removal_version was not supplied."""


class BadRemovalVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version was not a valid semver string."""


class NonDevRemovalVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version was not a pre-release version."""


class CodeRemovedError(Exception):
  """Indicates that the removal_version is not in the future.

  I.e., that the option/function/module with that removal_version has already been removed.

  Note, the code in question may not actually have been excised from the codebase yet, but
  it may be at any time, and no control paths access it.
  """


class BadDecoratorNestingError(DeprecationApplicationError):
  """Indicates the @deprecated decorator was innermost in a sequence of layered decorators."""


def get_deprecated_tense(removal_version, future_tense='will be', past_tense='was'):
  """Provides the grammatical tense for a given deprecated version vs the current version."""
  return future_tense if (Version(removal_version) >= PANTS_SEMVER) else past_tense


@memoized_method
def validate_removal_semver(removal_version):
  """Validates that removal_version is a valid semver.

  If so, returns that semver.  Raises an error otherwise.

  :param str removal_version: The pantsbuild.pants version which will remove the deprecated entity.
  :rtype: `packaging.version.Version`
  :raises DeprecationApplicationError: if the removal_version parameter is invalid.
  """
  if removal_version is None:
    raise MissingRemovalVersionError('The removal version must be provided.')
  if not isinstance(removal_version, six.string_types):
    raise BadRemovalVersionError('The removal_version must be a version string.')
  try:
    # NB: packaging will see versions like 1.a.0 as 1a0, and are "valid"
    # We explicitly want our versions to be of the form x.y.z.
    v = Version(removal_version)
    if len(v.base_version.split('.')) != 3:
      raise BadRemovalVersionError('The given removal version is not a valid version: '
                                   '{}'.format(removal_version))
    if not v.is_prerelease:
      raise NonDevRemovalVersionError('The given removal version is not a dev version: {}\n'
                                      'Features should generally be removed in the first `dev` release '
                                      'of a release cycle.'.format(removal_version))
    return v
  except InvalidVersion as e:
    raise BadRemovalVersionError('The given removal version {} is not a valid version: '
                                 '{}'.format(removal_version, e))


def get_frame_info(stacklevel, context=1):
  """Get a Traceback for the given `stacklevel`.

  For example:
  `stacklevel=0` means this function's frame (get_frame_info()).
  `stacklevel=1` means the calling function's frame.
  See https://docs.python.org/2/library/inspect.html#inspect.getouterframes for more info.

  NB: If `stacklevel` is greater than the number of actual frames, the outermost frame is used
  instead.
  """
  frame_list = inspect.getouterframes(inspect.currentframe(), context=context)
  frame_stack_index = stacklevel if stacklevel < len(frame_list) else len(frame_list) - 1
  return frame_list[frame_stack_index]


def warn_or_error(removal_version, deprecated_entity_description, hint=None, stacklevel=3,
                  frame_info=None, ensure_stderr=False):
  """Check the removal_version against the current pants version.

  Issues a warning if the removal version is > current pants version, or an error otherwise.

  :param string removal_version: The pantsbuild.pants version at which the deprecated entity
                                 will be/was removed.
  :param string deprecated_entity_description: A short description of the deprecated entity, that
                                            we can embed in warning/error messages.
  :param string hint: A message describing how to migrate from the removed entity.
  :param int stacklevel: The stacklevel to pass to warnings.warn.
  :param FrameInfo frame_info: If provided, use this frame info instead of getting one from
                               `stacklevel`.
  :param bool ensure_stderr: Whether use warnings.warn, or use warnings.showwarning to print
                             directly to stderr.
  :raises DeprecationApplicationError: if the removal_version parameter is invalid.
  :raises CodeRemovedError: if the current version is later than the version marked for removal.
  """
  removal_semver = validate_removal_semver(removal_version)

  msg = 'DEPRECATED: {} {} removed in version {}.'.format(deprecated_entity_description,
      get_deprecated_tense(removal_version), removal_version)
  if hint:
    msg += '\n  {}'.format(hint)

  # We need to have filename and line_number for warnings.formatwarning, which appears to be the only
  # way to get a warning message to display to stderr. We get that from frame_info -- it's too bad
  # we have to reconstruct the `stacklevel` logic ourselves, but we do also gain the ability to have
  # multiple lines of context, which is neat.
  if frame_info is None:
    frame_info = get_frame_info(stacklevel)
  _, filename, line_number, _, code_context, _ = frame_info
  if code_context:
    context_lines = ''.join(code_context)
  else:
    context_lines = '<no code context available>'

  if removal_semver > PANTS_SEMVER:
    if ensure_stderr:
      warning_msg = warnings.formatwarning(
        msg, DeprecationWarning, filename, line_number, line=context_lines)
      print(warning_msg, file=sys.stderr)
    else:
      warnings.showwarning(
        DeprecationWarning(msg) if PY2 else msg,
        DeprecationWarning,
        filename,
        line_number,
        line=context_lines)
  else:
    raise CodeRemovedError(msg)


def deprecated_conditional(predicate,
                           removal_version,
                           entity_description,
                           hint_message=None,
                           stacklevel=4):
  """Marks a certain configuration as deprecated.

  The predicate is used to determine if that configuration is deprecated. It is a function that
  will be called, if true, then the deprecation warning will issue.

  :param () -> bool predicate: A function that returns True if the deprecation warning should be on.
  :param string removal_version: The pants version which will remove the deprecated functionality.
  :param string entity_description: A description of the deprecated entity.
  :param string hint_message: An optional hint pointing to alternatives to the deprecation.
  :param int stacklevel: How far up in the stack do we go to find the calling fn to report
  :raises DeprecationApplicationError if the deprecation is applied improperly.
  """
  validate_removal_semver(removal_version)
  if predicate():
    warn_or_error(removal_version, entity_description, hint_message, stacklevel=stacklevel)


def deprecated(removal_version, hint_message=None, subject=None, ensure_stderr=False):
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
  :param str subject: The name of the subject that has been deprecated for logging clarity. Defaults
                      to the name of the decorated function/method.
  :param bool ensure_stderr: Forwarded to `ensure_stderr` in warn_or_error().
  :raises DeprecationApplicationError if the @deprecation is applied improperly.
  """
  validate_removal_semver(removal_version)
  def decorator(func):
    if not inspect.isfunction(func):
      raise BadDecoratorNestingError('The @deprecated decorator must be applied innermost of all '
                                     'decorators.')

    func_full_name = '{}.{}'.format(func.__module__, func.__name__)

    @wraps(func)
    def wrapper(*args, **kwargs):
      warn_or_error(removal_version, subject or func_full_name, hint_message,
                    ensure_stderr=ensure_stderr)
      return func(*args, **kwargs)
    return wrapper
  return decorator


def deprecated_module(removal_version, hint_message=None):
  """Marks an entire module as deprecated.

  Add a call to this at the top of the deprecated module, and it will print a warning message
  when the module is imported.

  Arguments are as for deprecated(), above.
  """
  warn_or_error(removal_version, 'module', hint_message)
