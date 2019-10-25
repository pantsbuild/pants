# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import sys
import warnings
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Iterator, Optional

from packaging.version import InvalidVersion, Version

from pants.util.memo import memoized_method
from pants.version import PANTS_SEMVER


class DeprecationApplicationError(Exception):
  """The base exception type thrown for any form of @deprecation application error."""


class MissingSemanticVersionError(DeprecationApplicationError):
  """Indicates the required removal_version was not supplied."""


class BadSemanticVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version was not a valid semver string."""


class NonDevSemanticVersionError(DeprecationApplicationError):
  """Indicates the supplied removal_version was not a pre-release version."""


class InvalidSemanticVersionOrderingError(DeprecationApplicationError):
  """Indicates that multiple semantic version strings were provided in an inconsistent ordering."""


class CodeRemovedError(Exception):
  """Indicates that the removal_version is not in the future.

  I.e., that the option/function/module with that removal_version has already been removed.

  Note, the code in question may not actually have been excised from the codebase yet, but
  it may be at any time, and no control paths access it.
  """


class BadDecoratorNestingError(DeprecationApplicationError):
  """Indicates the @deprecated decorator was innermost in a sequence of layered decorators."""


def get_deprecated_tense(
  removal_version: str, future_tense: str = 'will be', past_tense: str = 'was'
) -> str:
  """Provides the grammatical tense for a given deprecated version vs the current version."""
  return future_tense if (Version(removal_version) >= PANTS_SEMVER) else past_tense


@memoized_method
def validate_deprecation_semver(version_string: str, version_description: str) -> Version:
  """Validates that version_string is a valid semver.

  If so, returns that semver.  Raises an error otherwise.

  :param version_string: A pantsbuild.pants version which affects some deprecated entity.
  :param version_description: A string used in exception messages to describe what the
                              `version_string` represents.
  :raises DeprecationApplicationError: if the version_string parameter is invalid.
  """
  if version_string is None:
    raise MissingSemanticVersionError('The {} must be provided.'.format(version_description))
  if not isinstance(version_string, str):
    raise BadSemanticVersionError('The {} must be a version string.'.format(version_description))
  try:
    # NB: packaging will see versions like 1.a.0 as 1a0, and are "valid"
    # We explicitly want our versions to be of the form x.y.z.
    v = Version(version_string)
    if len(v.base_version.split('.')) != 3:
      raise BadSemanticVersionError('The given {} is not a valid version: '
                                   '{}'.format(version_description, version_string))
    if not v.is_prerelease:
      raise NonDevSemanticVersionError('The given {} is not a dev version: {}\n'
                                      'Features should generally be removed in the first `dev` release '
                                      'of a release cycle.'.format(version_description, version_string))
    return v
  except InvalidVersion as e:
    raise BadSemanticVersionError('The given {} {} is not a valid version: '
                                 '{}'.format(version_description, version_string, e))


def _get_frame_info(stacklevel: int, context: int = 1) -> inspect.FrameInfo:
  """Get a Traceback for the given `stacklevel`.

  For example:
  `stacklevel=0` means this function's frame (_get_frame_info()).
  `stacklevel=1` means the calling function's frame.
  See https://docs.python.org/2/library/inspect.html#inspect.getouterframes for more info.

  NB: If `stacklevel` is greater than the number of actual frames, the outermost frame is used
  instead.
  """
  frame_list = inspect.getouterframes(inspect.currentframe(), context=context)
  frame_stack_index = stacklevel if stacklevel < len(frame_list) else len(frame_list) - 1
  return frame_list[frame_stack_index]


@contextmanager
def _greater_warnings_context(context_lines_string: str) -> Iterator[None]:
  """Provide the `line` argument to warnings.showwarning().

  warnings.warn_explicit() doesn't use the `line` argument to showwarning(), but we want to
  make use of the warning filtering provided by warn_explicit(). This contextmanager overwrites the
  showwarning() method to pipe in the desired amount of context lines when using warn_explicit().
  """
  prev_showwarning = warnings.showwarning

  def wrapped(message, category, filename, lineno, file=None, line=None):
    return prev_showwarning(
      message=message,
      category=category,
      filename=filename,
      lineno=lineno,
      file=file,
      line=(line or context_lines_string))
  warnings.showwarning = wrapped
  yield
  warnings.showwarning = prev_showwarning


# TODO: propagate `deprecation_start_version` to other methods in this file!
def warn_or_error(
  removal_version: str,
  deprecated_entity_description: str,
  hint: Optional[str] = None,
  deprecation_start_version: Optional[str] = None,
  stacklevel: int = 3,
  frame_info: Optional[inspect.FrameInfo] = None,
  context: int = 1,
  ensure_stderr: bool = False
) -> None:
  """Check the removal_version against the current pants version.

  Issues a warning if the removal version is > current pants version, or an error otherwise.

  :param removal_version: The pantsbuild.pants version at which the deprecated entity will
                          be/was removed.
  :param deprecated_entity_description: A short description of the deprecated entity, that
                                        we can embed in warning/error messages.
  :param hint: A message describing how to migrate from the removed entity.
  :param deprecation_start_version: The pantsbuild.pants version at which the entity will
                                    begin to display a deprecation warning. This must be less
                                    than the `removal_version`. If not provided, the
                                    deprecation warning is always displayed.
  :param stacklevel: The stacklevel to pass to warnings.warn.
  :param frame_info: If provided, use this frame info instead of getting one from `stacklevel`.
  :param context: The number of lines of source code surrounding the selected frame to display
                  in a warning message.
  :param ensure_stderr: Whether use warnings.warn, or use warnings.showwarning to print
                        directly to stderr.
  :raises DeprecationApplicationError: if the removal_version parameter is invalid.
  :raises CodeRemovedError: if the current version is later than the version marked for removal.
  """
  removal_semver = validate_deprecation_semver(removal_version, 'removal version')
  if deprecation_start_version:
    deprecation_start_semver = validate_deprecation_semver(
      deprecation_start_version, 'deprecation start version')
    if deprecation_start_semver >= removal_semver:
      raise InvalidSemanticVersionOrderingError(
        'The deprecation start version {} must be less than the end version {}.'
        .format(deprecation_start_version, removal_version))
    elif PANTS_SEMVER < deprecation_start_semver:
      return

  msg = 'DEPRECATED: {} {} removed in version {}.'.format(deprecated_entity_description,
      get_deprecated_tense(removal_version), removal_version)
  if hint:
    msg += '\n  {}'.format(hint)

  # We need to have filename and line_number for warnings.formatwarning, which appears to be the only
  # way to get a warning message to display to stderr. We get that from frame_info -- it's too bad
  # we have to reconstruct the `stacklevel` logic ourselves, but we do also gain the ability to have
  # multiple lines of context, which is neat.
  if frame_info is None:
    frame_info = _get_frame_info(stacklevel, context=context)
  _, filename, line_number, _, code_context, _ = frame_info
  if code_context:
    context_lines = ''.join(code_context)
  else:
    context_lines = '<no code context available>'

  if removal_semver > PANTS_SEMVER:
    if ensure_stderr:
      # No warning filters can stop us from printing this message directly to stderr.
      warning_msg = warnings.formatwarning(
        msg, DeprecationWarning, filename, line_number, line=context_lines)
      print(warning_msg, file=sys.stderr)
    else:
      # This output is filtered by warning filters.
      with _greater_warnings_context(context_lines):
        warnings.warn_explicit(
          message=msg,
          category=DeprecationWarning,
          filename=filename,
          lineno=line_number)
    return
  else:
    raise CodeRemovedError(msg)


def deprecated_conditional(
  predicate: Callable[[], bool],
  removal_version: str,
  entity_description: str,
  hint_message: Optional[str] = None,
  stacklevel: int = 4
) -> None:
  """Marks a certain configuration as deprecated.

  The predicate is used to determine if that configuration is deprecated. It is a function that
  will be called, if true, then the deprecation warning will issue.

  :param predicate: A function that returns True if the deprecation warning should be on.
  :param removal_version: The pants version which will remove the deprecated functionality.
  :param entity_description: A description of the deprecated entity.
  :param hint_message: An optional hint pointing to alternatives to the deprecation.
  :param stacklevel: How far up in the stack do we go to find the calling fn to report
  :raises DeprecationApplicationError if the deprecation is applied improperly.
  """
  validate_deprecation_semver(removal_version, 'removal version')
  if predicate():
    warn_or_error(removal_version, entity_description, hint_message, stacklevel=stacklevel)


def deprecated(
  removal_version: str,
  hint_message: Optional[str] = None,
  subject: Optional[str] = None,
  ensure_stderr: bool = False
):
  """Marks a function or method as deprecated.

  A removal version must be supplied and it must be greater than the current 'pantsbuild.pants'
  version.

  When choosing a removal version there is a natural tension between the code-base, which benefits
  from short deprecation cycles, and the user-base which may prefer to deal with deprecations less
  frequently.  As a rule of thumb, if the hint message can fully convey corrective action
  succinctly and you judge the impact to be on the small side (effects custom tasks as opposed to
  effecting BUILD files), lean towards the next release version as the removal version; otherwise,
  consider initiating a discussion to win consensus on a reasonable removal version.

  :param removal_version: The pantsbuild.pants version which will remove the deprecated
                              function.
  :param hint_message: An optional hint pointing to alternatives to the deprecation.
  :param subject: The name of the subject that has been deprecated for logging clarity. Defaults
                      to the name of the decorated function/method.
  :param ensure_stderr: Forwarded to `ensure_stderr` in warn_or_error().
  :raises DeprecationApplicationError if the @deprecation is applied improperly.
  """
  validate_deprecation_semver(removal_version, 'removal version')

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


def deprecated_module(removal_version: str, hint_message: Optional[str] = None) -> None:
  """Marks an entire module as deprecated.

  Add a call to this at the top of the deprecated module, and it will print a warning message
  when the module is imported.

  Arguments are as for deprecated(), above.
  """
  warn_or_error(removal_version, 'module', hint_message)
