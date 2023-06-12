#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import datetime
import logging
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent

import requests
from packaging.version import Version
from pants_release.common import die

logger = logging.getLogger(__name__)


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
    # Use the main branch for all dev releases, and for the first alpha (which creates a stable branch).
    use_main_branch = new_version.is_devrelease or (
        new_version.pre
        and "a0" == "".join(str(p) for p in new_version.pre)
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


def relevant_shas(prior: str, release_branch: str) -> list[str]:
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


class Category(Enum):
    NewFeatures = "new feature"
    UserAPIChanges = "user api change"
    PluginAPIChanges = "plugin api change"
    BugFixes = "bugfix"
    Performance = "performance"
    Documentation = "documentation"
    Internal = "internal"

    def heading(self):
        if self == Category.Internal:
            return "Internal (put these in a PR comment for review, not the release notes)"
        return " ".join(
            re.sub(r"([A-Z][a-z]+)", r" \1", re.sub(r"([A-Z]+)", r" \1", self.name)).split()
        )


@dataclass(frozen=True)
class Entry:
    category: Category | None
    text: str


def categorize(pr_num: str) -> Category | None:
    sys.stderr.write(f"Categorizing PR#{pr_num}... ")
    sys.stderr.flush()

    def complete_categorization(category: Category | str) -> Category | None:
        sys.stderr.write(f"{category}\n")
        return category if isinstance(category, Category) else None

    # See: https://docs.github.com/en/rest/reference/pulls
    response = requests.get(f"https://api.github.com/repos/pantsbuild/pants/pulls/{pr_num}")
    if not response.ok:
        return complete_categorization(
            f"Unable to categorize PR {pr_num}. HTTP error: "
            f"{response.status_code} {response.reason}"
        )
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as e:
        return complete_categorization(
            f"Unable to categorize PR {pr_num}. Problem decoding JSON response: {e}"
        )

    labels = data.get("labels", [])
    for label in labels:
        name = label.get("name", "")
        if name.startswith("category:"):
            try:
                return complete_categorization(Category(name[len("category:") :]))
            except ValueError:
                recognized_category_labels = " ".join(f"'category:{c.value}'" for c in Category)
                logger.warning(
                    f"Unrecognized category label {name!r}. Recognized category labels are: "
                    f"{recognized_category_labels}"
                )
    return complete_categorization("No recognized `category:*` label found.")


def prepare_sha(sha: str) -> Entry:
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
        return Entry(category=None, text=f"* {subject}")
    pr_num = pr_num_match.groups()[0]
    category = categorize(pr_num)
    pr_url = f"https://github.com/pantsbuild/pants/pull/{pr_num}"
    subject_with_url = subject.replace(f"(#{pr_num})", f"([#{pr_num}]({pr_url}))")
    return Entry(category=category, text=f"* {subject_with_url}")


def instructions(new_version: str, entries: list[Entry]) -> str:
    date = datetime.date.today().strftime("%b %d, %Y")
    version_components = new_version.split(".", maxsplit=4)
    major, minor = version_components[0], version_components[1]

    entries_by_category = defaultdict(list)
    for entry in entries:
        entries_by_category[entry.category].append(entry.text)

    def format_entries(category: Category | None) -> str:
        entries = entries_by_category.get(category, [])
        heading = category.heading() if category else "Uncategorized"
        lines = "\n\n".join(entries)
        if not entries:
            return ""
        return f"\n### {heading}\n\n{lines}\n"

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
        {{new_features}}{{user_api_changes}}{{plugin_api_changes}}{{bugfixes}}{{performance}}{{documentation}}{{internal}}
        --------------------------------------------------------------------
        {{uncategorized}}
        """
    ).format(
        new_features=format_entries(Category.NewFeatures),
        user_api_changes=format_entries(Category.UserAPIChanges),
        plugin_api_changes=format_entries(Category.PluginAPIChanges),
        bugfixes=format_entries(Category.BugFixes),
        performance=format_entries(Category.Performance),
        documentation=format_entries(Category.Documentation),
        internal=format_entries(Category.Internal),
        uncategorized=format_entries(None),
    )


def main() -> None:
    args = create_parser().parse_args()
    release_branch = determine_release_branch(args.new)
    entries = [prepare_sha(sha) for sha in relevant_shas(args.prior, release_branch)]
    print(instructions(args.new, entries))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
