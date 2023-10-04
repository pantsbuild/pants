# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import logging
from functools import wraps
from typing import Any, Callable, TypeVar

from packaging.version import InvalidVersion, Version

from pants.util.memo import memoized, memoized_method
from pants.version import PANTS_SEMVER

logger = logging.getLogger(__name__)


class DeprecationError(Exception):
    """The base exception type thrown for any form of @deprecation application error."""


class MissingSemanticVersionError(DeprecationError):
    """Indicates the required removal_version was not supplied."""


class BadSemanticVersionError(DeprecationError):
    """Indicates the supplied removal_version was not a valid semver string."""


class NonDevSemanticVersionError(DeprecationError):
    """Indicates the supplied removal_version was not a pre-release version."""


class InvalidSemanticVersionOrderingError(DeprecationError):
    """Indicates that multiple semantic version strings were provided in an inconsistent
    ordering."""


class BadDecoratorNestingError(DeprecationError):
    """Indicates the @deprecated decorator was innermost in a sequence of layered decorators."""


class CodeRemovedError(Exception):
    """Indicates that the removal_version is not in the future.

    I.e., that the option/function/module with that removal_version has already been removed.

    Note that the code in question may not actually have been excised from the codebase yet, but
    it may be at any time.
    """


def is_deprecation_active(start_version: str | None) -> bool:
    return start_version is None or Version(start_version) <= PANTS_SEMVER


def get_deprecated_tense(removal_version: str) -> str:
    """Provides the grammatical tense for a given deprecated version vs the current version."""
    return "is scheduled to be" if (Version(removal_version) >= PANTS_SEMVER) else "was"


@memoized_method
def validate_deprecation_semver(version_string: str, version_description: str) -> Version:
    """Validates that version_string is a valid semver.

    If so, returns that semver. Raises an error otherwise.

    :param version_string: A pantsbuild.pants version which affects some deprecated entity.
    :param version_description: A string used in exception messages to describe what the
        `version_string` represents.
    :raises DeprecationError: if the version_string parameter is invalid.
    """
    if version_string is None:
        raise MissingSemanticVersionError(f"The {version_description} must be provided.")
    if not isinstance(version_string, str):
        raise BadSemanticVersionError(
            f"The {version_description} must be a version string but was {version_string} with "
            f"type {type(version_string)}."
        )

    try:
        v = Version(version_string)
    except InvalidVersion as e:
        raise BadSemanticVersionError(
            f"The given {version_description} {version_string} is not a valid version: "
            f"{repr(e)}"
        )

    # NB: packaging.Version will see versions like 1.a.0 as 1a0 and as "valid".
    # We explicitly want our versions to be of the form x.y.z.
    if len(v.base_version.split(".")) != 3:
        raise BadSemanticVersionError(
            f"The given {version_description} is not a valid version: "
            f"{version_description}. Expecting the format `x.y.z.dev0`"
        )
    if not v.is_prerelease:
        raise NonDevSemanticVersionError(
            f"The given {version_description} is not a dev version: {version_string}\n"
            "Features should generally be removed in the first `dev` release of a release "
            "cycle."
        )
    return v


@memoized
def warn_or_error(
    removal_version: str,
    entity: str,
    hint: str | None,
    *,
    start_version: str | None = None,
    print_warning: bool = True,
    stacklevel: int = 0,
    context: int = 1,
) -> None:
    """Check the removal_version against the current Pants version.

    When choosing a removal version, there is a natural tension between the code-base, which benefits
    from short deprecation cycles, and the user-base which may prefer to deal with deprecations less
    frequently. As a rule of thumb, if the hint message can fully convey corrective action
    succinctly and you judge the impact to be on the small side (effects custom tasks as opposed to
    effecting BUILD files), lean towards the next release version as the removal version; otherwise,
    consider initiating a discussion to win consensus on a reasonable removal version.

    Issues a warning if the removal version is > current Pants version or an error otherwise.

    :param removal_version: The pantsbuild.pants version at which the deprecated entity will
        be/was removed.
    :param entity: A short description of the deprecated entity, e.g. "using an INI config file".
    :param hint: How to migrate.
    :param start_version: The pantsbuild.pants version at which the entity will
        begin to display a deprecation warning. This must be less than the `removal_version`. If
        not provided, the deprecation warning is always displayed.
    :param print_warning: Whether to print a warning for deprecations *before* their removal.
        If this flag is off, an exception will still be raised for options past their deprecation
        date.
    :param stacklevel: How far up the call stack to go for blame. Use 0 to disable.
    :param context: How many lines of source context to include.
    :raises DeprecationError: if the removal_version parameter is invalid.
    :raises CodeRemovedError: if the current version is later than the version marked for removal.
    """
    removal_semver = validate_deprecation_semver(removal_version, "removal version")
    if start_version:
        start_semver = validate_deprecation_semver(start_version, "deprecation start version")
        if start_semver >= removal_semver:
            raise InvalidSemanticVersionOrderingError(
                f"The deprecation start version {start_version} must be less than "
                f"the end version {removal_version}."
            )
        elif PANTS_SEMVER < start_semver:
            return

    msg = (
        f"DEPRECATED: {entity} {get_deprecated_tense(removal_version)} removed in version "
        f"{removal_version}."
    )
    if stacklevel > 0:
        # Get stack frames, ignoring those for internal/builtin code.
        frames = [frame for frame in inspect.stack(context) if frame.index is not None]
        if stacklevel < len(frames):
            frame = frames[stacklevel]
            code_context = "    ".join(frame.code_context) if frame.code_context else ""
            msg += f"\n ==> {frame.filename}:{frame.lineno}\n    {code_context}"
    if hint:
        msg += f"\n\n{hint}"

    if removal_semver <= PANTS_SEMVER:
        raise CodeRemovedError(msg)
    if print_warning:
        logger.warning(msg)


def deprecated_conditional(
    predicate: Callable[[], bool],
    removal_version: str,
    entity: str,
    hint: str | None,
    *,
    start_version: str | None = None,
) -> None:
    """Mark something as deprecated if the predicate is true."""
    validate_deprecation_semver(removal_version, "removal version")
    if predicate():
        warn_or_error(removal_version, entity, hint, start_version=start_version)


ReturnType = TypeVar("ReturnType")


def deprecated(
    removal_version: str,
    hint: str | None = None,
    *,
    start_version: str | None = None,
) -> Callable[[Callable[..., ReturnType]], Callable[..., ReturnType]]:
    """Mark a function or method as deprecated."""
    validate_deprecation_semver(removal_version, "removal version")

    def decorator(func):
        if not inspect.isfunction(func):
            raise BadDecoratorNestingError(
                "The @deprecated decorator must be applied innermost of all decorators."
            )

        @wraps(func)
        def wrapper(*args, **kwargs):
            warn_or_error(
                removal_version,
                f"{func.__module__}.{func.__qualname__}()",
                hint,
                start_version=start_version,
                stacklevel=3,
                context=3,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def deprecated_module(
    removal_version: str, hint: str | None, *, start_version: str | None = None
) -> None:
    """Mark an entire module as deprecated.

    Add a call to this at the top of the deprecated module.
    """
    warn_or_error(removal_version, "module", hint, start_version=start_version)


# TODO: old_container and new_container are both `OptionValueContainer`, but that causes a dep
#  cycle.
def resolve_conflicting_options(
    *,
    old_option: str,
    new_option: str,
    old_scope: str,
    new_scope: str,
    old_container: Any,
    new_container: Any,
) -> Any:
    """Utility for resolving an option that's been migrated to a new location.

    This will check if either option was explicitly configured, and if so, use that. If both were
    configured, it will error. Otherwise, it will use the default value for the new, preferred
    option.

    The option names should use snake_case, rather than --kebab-case.
    """
    old_configured = not old_container.is_default(old_option)
    new_configured = not new_container.is_default(new_option)
    if old_configured and new_configured:

        def format_option(*, scope: str, option: str) -> str:
            scope_preamble = "--" if scope == "" else f"--{scope}-"
            return f"`{scope_preamble}{option}`".replace("_", "-")

        old_display = format_option(scope=old_scope, option=old_option)
        new_display = format_option(scope=new_scope, option=new_option)
        raise ValueError(
            f"Conflicting options used. You used the new, preferred {new_display}, but also "
            f"used the deprecated {old_display}.\n\nPlease use only one of these "
            f"(preferably {new_display})."
        )
    if old_configured:
        return old_container.get(old_option)
    return new_container.get(new_option)
