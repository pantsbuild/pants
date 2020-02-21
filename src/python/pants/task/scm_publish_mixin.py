# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import traceback
from abc import abstractmethod
from functools import total_ordering

from pants.base.exceptions import TaskError
from pants.scm.scm import Scm


class Version:
    @staticmethod
    def parse(version):
        """Attempts to parse the given string as Semver, then falls back to Namedver."""
        try:
            return Semver.parse(version)
        except ValueError:
            return Namedver.parse(version)

    @abstractmethod
    def version(self):
        """Returns the string representation of this Version."""


@total_ordering
class Namedver(Version):
    """A less restrictive versioning scheme that does not conflict with Semver.

    Its important to not allow certain characters that are used in maven for performing
    range matching like *><=!  See:

    https://maven.apache.org/enforcer/enforcer-rules/versionRanges.html
    """

    _VALID_NAME = re.compile("^[-_.A-Za-z0-9]+$")
    _INVALID_NAME = re.compile("^[-_.]*$")

    @classmethod
    def parse(cls, version):
        # must not contain whitespace
        if not cls._VALID_NAME.match(version):
            raise ValueError(
                "Named versions must match {}: '{}'".format(cls._VALID_NAME.pattern, version)
            )
        if cls._INVALID_NAME.match(version):
            raise ValueError("Named version must contain at least one alphanumeric character")

        # must not be valid semver
        try:
            Semver.parse(version)
        except ValueError:
            return Namedver(version)
        else:
            raise ValueError(
                "Named versions must not be valid semantic versions: '{0}'".format(version)
            )

    def __init__(self, version):
        self._version = version

    def version(self):
        return self._version

    def __eq__(self, other):
        return self._version == other._version

    def __lt__(self, other):
        raise ValueError("{0} is not comparable to {1}".format(self, other))

    def __repr__(self):
        return "Namedver({0})".format(self.version())


@total_ordering
class Semver(Version):
    """Semantic versioning.

    See http://semver.org
    """

    @staticmethod
    def parse(version):
        components = version.split(".", 3)
        if len(components) != 3:
            raise ValueError
        major, minor, patch = components

        def to_i(component):
            try:
                return int(component)
            except (TypeError, ValueError):
                raise ValueError(
                    "Invalid revision component {} in {} - "
                    "must be an integer".format(component, version)
                )

        return Semver(to_i(major), to_i(minor), to_i(patch))

    def __init__(self, major, minor, patch, snapshot=False):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.snapshot = snapshot

    def bump(self):
        # A bump of a snapshot discards snapshot status
        return Semver(self.major, self.minor, self.patch + 1)

    def make_snapshot(self):
        return Semver(self.major, self.minor, self.patch, snapshot=True)

    def version(self):
        return "{}.{}.{}".format(
            self.major,
            self.minor,
            ("{}-SNAPSHOT".format(self.patch)) if self.snapshot else self.patch,
        )

    def __eq__(self, other):
        return (self.major, self.minor, self.patch, self.snapshot) == (
            other.major,
            other.minor,
            other.patch,
            other.snapshot,
        )

    def __lt__(self, other):
        diff = self.major - other.major
        if diff:
            return self.major < other.major
        diff = self.minor - other.minor
        if diff:
            return self.patch < other.patch
        return self.snapshot < other.snapshot

    def __repr__(self):
        return "Semver({})".format(self.version())


class ScmPublishMixin:
    """A mixin for tasks that provides methods for publishing pushdbs via scm.

    Requires that the mixing task class
    * has the properties scm and log,
    * has the method get_options
    """

    class InvalidBranchError(TaskError):
        """Indicates the current branch is not an allowed branch to publish from."""

    class InvalidRemoteError(TaskError):
        """Indicates the current default remote server is not an allowed remote server to publish
        to."""

    class DirtyWorkspaceError(TaskError):
        """Indicates the current workspace is dirty and thus unsuitable for publishing from."""

    _SCM_PUSH_ATTEMPTS = 5

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--scm-push-attempts",
            type=int,
            default=cls._SCM_PUSH_ATTEMPTS,
            help="Try pushing the pushdb to the SCM this many times before aborting.",
        )
        register(
            "--restrict-push-branches",
            advanced=True,
            type=list,
            help="Allow pushes only from one of these branches.",
        )
        register(
            "--restrict-push-urls",
            advanced=True,
            type=list,
            help="Allow pushes to only one of these urls.",
        )
        register(
            "--verify-commit",
            advanced=True,
            type=bool,
            default=True,
            help='Whether or not to "verify" commits made using SCM publishing. For git, this '
            "means running commit hooks.",
        )

    @property
    def restrict_push_branches(self):
        return self.get_options().restrict_push_branches

    @property
    def restrict_push_urls(self):
        return self.get_options().restrict_push_urls

    @property
    def scm_push_attempts(self):
        return self.get_options().scm_push_attempts

    def check_clean_master(self, commit=False):
        """Perform a sanity check on SCM publishing constraints.

        Checks for uncommitted tracked files and ensures we're on an allowed branch configured to push
        to an allowed server if `commit` is `True`.

        :param bool commit: `True` if a commit is in progress.
        :raise TaskError: on failure
        """
        if commit:
            if self.restrict_push_branches:
                branch = self.scm.branch_name
                if branch not in self.restrict_push_branches:
                    raise self.InvalidBranchError(
                        "Can only push from {}, currently on branch: {}".format(
                            " ".join(sorted(self.restrict_push_branches)), branch
                        )
                    )

            if self.restrict_push_urls:
                url = self.scm.server_url
                if url not in self.restrict_push_urls:
                    raise self.InvalidRemoteError(
                        "Can only push to {}, currently the remote url is: {}".format(
                            " ".join(sorted(self.restrict_push_urls)), url
                        )
                    )

            changed_files = self.scm.changed_files()
            if changed_files:
                raise self.DirtyWorkspaceError(
                    "Can only push from a clean branch, found : {}".format(" ".join(changed_files))
                )
        elif self.scm:
            self.log.info(
                "Skipping check for a clean {} branch in test mode.".format(self.scm.branch_name)
            )

    def commit_pushdb(self, coordinates, postscript=None):
        """Commit changes to the pushdb with a message containing the provided coordinates."""
        self.scm.commit(
            "pants build committing publish data for push of {coordinates}"
            "{postscript}".format(coordinates=coordinates, postscript=postscript or ""),
            verify=self.get_options().verify_commit,
        )

    def publish_pushdb_changes_to_remote_scm(
        self, pushdb_file, coordinate, tag_name, tag_message, postscript=None
    ):
        """Push pushdb changes to the remote scm repository, and then tag the commit if it
        succeeds."""

        self._add_pushdb(pushdb_file)
        self.commit_pushdb(coordinate, postscript=postscript)
        self._push_and_tag_changes(
            tag_name=tag_name,
            tag_message="{message}{postscript}".format(
                message=tag_message, postscript=postscript or ""
            ),
        )

    def _add_pushdb(self, pushdb_file):
        self.scm.add(pushdb_file)

    def _push_and_tag_changes(self, tag_name, tag_message):
        self._push_with_retry(self.scm, self.log, self.scm_push_attempts)
        self.scm.tag(tag_name, tag_message)

    @staticmethod
    def _push_with_retry(scm, log, attempts):
        global_scm_exception = None
        for attempt in range(attempts):
            try:
                log.debug("Trying scm push")
                scm.push()
                break  # success
            except Scm.RemoteException as scm_exception:
                global_scm_exception = scm_exception
                log.debug("Scm push failed, trying to refresh.")
                # This might fail in the event that there is a real conflict, throwing
                # a Scm.LocalException (in case of a rebase failure) or a Scm.RemoteException
                # in the case of a fetch failure.  We'll directly raise a local exception,
                # since we can't fix it by retrying, but if we do, we want to display the
                # remote exception that caused the refresh as well just in case the user cares.
                # Remote exceptions probably indicate network or configuration issues, so
                # we'll let them propagate
                try:
                    scm.refresh(leave_clean=True)
                except Scm.LocalException as local_exception:
                    exc = traceback.format_exc()
                    log.debug("SCM exception while pushing: {}".format(exc))
                    raise local_exception

        else:  # no more retries
            raise global_scm_exception
