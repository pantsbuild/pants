# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import logging
from functools import wraps
from typing import Any, Callable, Optional

from packaging.version import InvalidVersion, Version

from pants.util.memo import memoized_method
from pants.version import PANTS_SEMVER

logger = logging.getLogger(__name__)


class DeprecationApplicationError(Exception):
    """The base exception type thrown for any form of @deprecation application error."""


class MissingSemanticVersionError(DeprecationApplicationError):
    """Indicates the required removal_version was not supplied."""


class BadSemanticVersionError(DeprecationApplicationError):
    """Indicates the supplied removal_version was not a valid semver string."""


class NonDevSemanticVersionError(DeprecationApplicationError):
    """Indicates the supplied removal_version was not a pre-release version."""


class InvalidSemanticVersionOrderingError(DeprecationApplicationError):
    """Indicates that multiple semantic version strings were provided in an inconsistent
    ordering."""


class CodeRemovedError(Exception):
    """Indicates that the removal_version is not in the future.

    I.e., that the option/function/module with that removal_version has already been removed.

    Note, the code in question may not actually have been excised from the codebase yet, but
    it may be at any time, and no control paths access it.
    """


class BadDecoratorNestingError(DeprecationApplicationError):
    """Indicates the @deprecated decorator was innermost in a sequence of layered decorators."""


def is_deprecation_active(deprecation_start_version: Optional[str]) -> bool:
    return deprecation_start_version is None or Version(deprecation_start_version) <= PANTS_SEMVER


def get_deprecated_tense(removal_version: str) -> str:
    """Provides the grammatical tense for a given deprecated version vs the current version."""
    return "will be" if (Version(removal_version) >= PANTS_SEMVER) else "was"


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
        raise MissingSemanticVersionError("The {} must be provided.".format(version_description))
    if not isinstance(version_string, str):
        raise BadSemanticVersionError(
            "The {} must be a version string.".format(version_description)
        )
    try:
        # NB: packaging will see versions like 1.a.0 as 1a0, and are "valid"
        # We explicitly want our versions to be of the form x.y.z.
        v = Version(version_string)
        if len(v.base_version.split(".")) != 3:
            raise BadSemanticVersionError(
                "The given {} is not a valid version: "
                "{}".format(version_description, version_string)
            )
        if not v.is_prerelease:
            raise NonDevSemanticVersionError(
                "The given {} is not a dev version: {}\n"
                "Features should generally be removed in the first `dev` release "
                "of a release cycle.".format(version_description, version_string)
            )
        return v
    except InvalidVersion as e:
        raise BadSemanticVersionError(
            "The given {} {} is not a valid version: "
            "{}".format(version_description, version_string, e)
        )


# TODO: propagate `deprecation_start_version` to other methods in this file!
def warn_or_error(
    removal_version: str,
    deprecated_entity_description: str,
    hint: Optional[str] = None,
    deprecation_start_version: Optional[str] = None,
    print_warning: bool = True,
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
    :param print_warning: Whether to print a warning for deprecations *before* their removal.
                          If this flag is off, an exception will still be raised for options
                          past their deprecation date.
    :raises DeprecationApplicationError: if the removal_version parameter is invalid.
    :raises CodeRemovedError: if the current version is later than the version marked for removal.
    """
    removal_semver = validate_deprecation_semver(removal_version, "removal version")
    if deprecation_start_version:
        deprecation_start_semver = validate_deprecation_semver(
            deprecation_start_version, "deprecation start version"
        )
        if deprecation_start_semver >= removal_semver:
            raise InvalidSemanticVersionOrderingError(
                f"The deprecation start version {deprecation_start_version} must be less than "
                f"the end version {removal_version}."
            )
        elif PANTS_SEMVER < deprecation_start_semver:
            return

    msg = (
        f"DEPRECATED: {deprecated_entity_description} {get_deprecated_tense(removal_version)} "
        f"removed in version {removal_version}."
    )
    if hint:
        msg += f"\n\n{hint}"

    if removal_semver <= PANTS_SEMVER:
        raise CodeRemovedError(msg)
    if print_warning:
        logger.warning(msg)


def deprecated_conditional(
    predicate: Callable[[], bool],
    removal_version: str,
    entity_description: str,
    hint_message: Optional[str] = None,
    deprecation_start_version: Optional[str] = None,
) -> None:
    """Marks a certain configuration as deprecated.

    The predicate is used to determine if that configuration is deprecated. It is a function that
    will be called, if true, then the deprecation warning will issue.

    :param predicate: A function that returns True if the deprecation warning should be on.
    :param removal_version: The pants version which will remove the deprecated functionality.
    :param entity_description: A description of the deprecated entity.
    :param hint_message: An optional hint pointing to alternatives to the deprecation.
    :raises DeprecationApplicationError if the deprecation is applied improperly.
    """
    validate_deprecation_semver(removal_version, "removal version")
    if predicate():
        warn_or_error(
            removal_version,
            entity_description,
            hint_message,
            deprecation_start_version=deprecation_start_version,
        )


def deprecated(
    removal_version: str,
    hint_message: Optional[str] = None,
    subject: Optional[str] = None,
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
    :raises DeprecationApplicationError if the @deprecation is applied improperly.
    """
    validate_deprecation_semver(removal_version, "removal version")

    def decorator(func):
        if not inspect.isfunction(func):
            raise BadDecoratorNestingError(
                "The @deprecated decorator must be applied innermost of all " "decorators."
            )

        func_full_name = "{}.{}".format(func.__module__, func.__name__)

        @wraps(func)
        def wrapper(*args, **kwargs):
            warn_or_error(
                removal_version,
                subject or func_full_name,
                hint_message,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def deprecated_module(
    removal_version: str,
    hint_message: Optional[str] = None,
    *,
    deprecation_start_version: Optional[str] = None,
) -> None:
    """Marks an entire module as deprecated.

    Add a call to this at the top of the deprecated module, and it will print a warning message
    when the module is imported.

    :param removal_version: The pantsbuild.pants version which will remove the deprecated
                            function.
    :param hint_message: An optional hint pointing to alternatives to the deprecation.
    """
    warn_or_error(
        removal_version,
        "module",
        hint_message,
        deprecation_start_version=deprecation_start_version,
    )


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
