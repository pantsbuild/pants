#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import datetime
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import requests
from packaging.version import Version
from pants_release.git import git, git_fetch

from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the changelog for a release.")
    parser.add_argument(
        "--prior",
        required=True,
        type=Version,
        help="The version of the prior release, e.g. `2.0.0.dev0` or `2.0.0rc1`.",
    )
    parser.add_argument(
        "--new",
        required=True,
        type=Version,
        help="The version for the new release, e.g. `2.0.0.dev1` or `2.0.0rc2`.",
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

    def notes_file_name(self) -> Path:
        return Path(f"src/python/pants/notes/{self.slug}.md")


def relevant_shas(prior: Version, release_ref: str) -> list[str]:
    prior_tag = f"release_{prior}"
    return git("log", "--format=format:%H", release_ref, f"^{prior_tag}").splitlines()


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
    subject = git("log", "-1", "--format=format:%s", sha)
    pr_num_match = re.search(r"\(#(\d{4,5})\)\s*$", subject)
    if not pr_num_match:
        return Entry(category=None, text=f"* {subject}")
    pr_num = pr_num_match.groups()[0]
    category = categorize(pr_num)
    pr_url = f"https://github.com/pantsbuild/pants/pull/{pr_num}"
    subject_with_url = subject.replace(f"(#{pr_num})", f"([#{pr_num}]({pr_url}))")
    return Entry(category=category, text=f"* {subject_with_url}")


def instructions(release_info: ReleaseInfo, entries: list[Entry]) -> str:
    date = datetime.date.today().strftime("%b %d, %Y")

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

    return softwrap(
        f"""\
        Copy the below headers into `{release_info.notes_file_name()}`. Then, put each
        external-facing commit into the relevant category. Commits that are internal-only (i.e.,
        that are only of interest to Pants developers and have no user-facing implications) should
        be pasted into a PR comment for review, not the release notes.

        You can tweak descriptions to be more descriptive or to fix typos, and you can reorder
        based on relative importance to end users. Delete any unused headers.

        ---------------------------------------------------------------------

        ## {release_info.version} ({date})

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
    release_info = ReleaseInfo.determine(args.new)
    branch_sha = git_fetch(release_info.branch)
    entries = [prepare_sha(sha) for sha in relevant_shas(args.prior, branch_sha)]
    print(instructions(release_info, entries))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
