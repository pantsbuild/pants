#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import datetime
import re
import subprocess
from textwrap import dedent
from typing import List

from common import die
from packaging.version import Version


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the changelog for a release.")
    parser.add_argument(
        "--prior",
        required=True,
        type=str,
        help="The version of the prior release, e.g. `2.0.0.dev0` or `2.0.0rc1`.",
    )
    parser.add_argument(
        "--new",
        required=True,
        type=str,
        help="The version for the new release, e.g. `2.0.0.dev1` or `2.0.0rc2`.",
    )
    return parser


def determine_release_branch(new_version_str: str) -> str:
    new_version = Version(new_version_str)
    # Use the main branch for all dev releases, and for the first rc (which creates a stable branch).
    use_main_branch = new_version.is_devrelease or (
        new_version.pre
        and "rc0" == "".join(str(p) for p in new_version.pre)
        and new_version.micro == 0
    )
    release_branch = "main" if use_main_branch else f"{new_version.major}.{new_version.minor}.x"
    branch_confirmation = input(
        f"Have you recently pulled from upstream on the branch `{release_branch}`? "
        "This is needed to ensure the changelog is exhaustive. [Y/n]"
    )
    if branch_confirmation and branch_confirmation.lower() != "y":
        die(f"Please checkout to the branch `{release_branch}` and pull from upstream. ")
    return release_branch


def relevant_shas(prior: str, release_branch: str) -> List[str]:
    prior_tag = f"release_{prior}"
    return (
        subprocess.run(
            ["git", "log", "--format=format:%H", release_branch, f"^{prior_tag}"],
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode()
        .splitlines()
    )


def prepare_sha(sha: str) -> str:
    subject = (
        subprocess.run(
            ["git", "log", "-1", "--format=format:%s", sha],
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode()
        .strip()
    )
    pr_num_match = re.search(r"\(#(\d{4,5})\)\s*$", subject)
    if not pr_num_match:
        return f"* {subject}"
    pr_num = pr_num_match.groups()[0]
    pr_url = f"https://github.com/pantsbuild/pants/pull/{pr_num}"
    subject_with_url = subject.replace(f"(#{pr_num})", f"([#{pr_num}]({pr_url}))")
    return f"* {subject_with_url}"


def instructions(new_version: str) -> str:
    date = datetime.date.today().strftime("%b %d, %Y")
    version_components = new_version.split(".", maxsplit=4)
    major, minor = version_components[0], version_components[1]
    return dedent(
        f"""\
        Copy the below headers into `src/python/pants/notes/{major}.{minor}.x.md`. Then, put each
        external-facing commit into the relevant category. Commits that are internal-only (i.e.,
        that are only of interest to Pants developers and have no user-facing implications) should
        be pasted into a PR comment for review, not the release notes.

        You can tweak descriptions to be more descriptive or to fix typos, and you can reorder
        based on relative importance to end users. Delete any unused headers.

        ---------------------------------------------------------------------

        ## {new_version} ({date})

        ### New Features


        ### User API Changes


        ### Plugin API Changes


        ### Bug fixes


        ### Performance


        ### Documentation


        ### Internal (put these in a PR comment for review, not the release notes)

        --------------------------------------------------------------------

        """
    )


def main() -> None:
    args = create_parser().parse_args()
    release_branch = determine_release_branch(args.new)

    print(instructions(args.new))
    entries = [prepare_sha(sha) for sha in relevant_shas(args.prior, release_branch)]
    print("\n\n".join(entries))


if __name__ == "__main__":
    main()
