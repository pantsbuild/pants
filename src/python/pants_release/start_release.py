#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import github
from packaging.version import Version
from pants_release.common import CONTRIBUTORS_PATH, VERSION_PATH, die, sorted_contributors
from pants_release.git import git, git_fetch, github_repo

from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the changelog for a release.")
    parser.add_argument(
        "--new",
        required=True,
        type=Version,
        help="The version for the new release, e.g. `2.0.0.dev1` or `2.0.0rc2`.",
    )
    parser.add_argument(
        "--release-manager",
        required=True,
        help="The GitHub username of the person managing this release",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help=softwrap(
            """
            Publish the changes: create a branch, commit, push, and create a pull request. Ensure
            `gh` (https://cli.github.com) is installed and authenticated.
            """
        ),
    )
    return parser


@dataclass(frozen=True)
class ReleaseInfo:
    version: Version
    slug: str
    branch: str

    @staticmethod
    def determine(new_version: Version) -> ReleaseInfo:
        slug = f"{new_version.major}.{new_version.minor}.x"
        # Use the main branch for all dev releases, and for the first alpha (which creates a stable branch).
        use_main_branch = new_version.is_devrelease or (
            new_version.pre
            and "a0" == "".join(str(p) for p in new_version.pre)
            and new_version.micro == 0
        )
        branch = "main" if use_main_branch else slug
        return ReleaseInfo(version=new_version, slug=slug, branch=branch)


def update_contributors() -> None:
    CONTRIBUTORS_PATH.write_text(
        "Created as part of the release process.\n\n"
        + "".join(f"+ {c}\n" for c in sorted_contributors(git_range="HEAD"))
    )


def update_version(release_info: ReleaseInfo) -> None:
    VERSION_PATH.write_text(f"{release_info.version}\n")


def commit_and_pr(
    repo: github.Repository.Repository,
    release_info: ReleaseInfo,
    release_manager: str,
) -> None:
    title = f"Prepare {release_info.version}"
    branch = f"automation/release/{release_info.version}"

    # starting from HEAD, because we checked out the relevant branch
    git("checkout", "-b", branch)
    git("add", str(VERSION_PATH), str(CONTRIBUTORS_PATH))
    git("commit", "-m", title)
    git("push", "git@github.com:pantsbuild/pants.git", "HEAD")

    pr = repo.create_pull(
        title=title,
        body="",
        base=release_info.branch,
        head=branch,
    )
    pr.add_to_labels("automation:release-prep", "category:internal")
    pr.add_to_assignees(release_manager)


def main() -> None:
    args = create_parser().parse_args()
    logging.basicConfig(level=args.log_level)

    if args.new < Version("2.18.0.dev0"):
        die(
            softwrap(
                """
                This script shouldn't be used for releases pre-2.18.x.
                Follow the release docs for the relevant release.

                E.g. https://www.pantsbuild.org/v2.17/docs/release-process
                """
            )
        )

    # connect to github first, to fail faster if credentials are wrong, etc.
    gh_repo = github_repo() if args.publish else None

    release_info = ReleaseInfo.determine(args.new)

    git("checkout", git_fetch(release_info.branch))

    update_contributors()
    update_version(release_info)

    if args.publish:
        assert gh_repo is not None
        commit_and_pr(gh_repo, release_info, args.release_manager)


if __name__ == "__main__":
    main()
