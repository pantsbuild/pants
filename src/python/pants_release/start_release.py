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
from pants_release.common import CONTRIBUTORS_PATH, VERSION_PATH, sorted_contributors
from pants_release.git import git, git_fetch, github_pr_create

from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

BASE_PR_BODY = softwrap(
    """
    This PR is release preparation. Please read over the release notes and make adjustments for
    clarity for users, such as:

    - shuffle miscategorised items to a better category (including completely uncategorised items)

    - fix or improve poor titles, like "fix bug", so they are more accurate or descriptive (check to
      see if the PR title is better).

    - fix typos

    Once satisfied, approve and merge, as normal.

    ---
    """
)


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


def relevant_shas(release_ref: str) -> list[str]:
    # infer the changes since the most recent previous release on this branch
    prior_tag = git("describe", "--tags", "--abbrev=0", release_ref)
    print(f"Found prior tag: {prior_tag}", file=sys.stderr)
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


@dataclass(frozen=True)
class Formatted:
    external: str
    internal: str


def format_notes(release_info: ReleaseInfo, entries: list[Entry], date: datetime.date) -> Formatted:
    entries_by_category = defaultdict(list)
    for entry in entries:
        entries_by_category[entry.category].append(entry.text)

    def format_entries(category: Category | None) -> str:
        entries = entries_by_category.get(category, [])
        heading = category.heading() if category else "Uncategorized"
        lines = "\n\n".join(entries)
        if not entries:
            return ""
        return f"### {heading}\n\n{lines}"

    external_categories = [
        Category.NewFeatures,
        Category.UserAPIChanges,
        Category.PluginAPIChanges,
        Category.BugFixes,
        Category.Performance,
        Category.Documentation,
        # ensure uncategorized entries appear
        None,
    ]

    external = "\n\n".join(
        [
            f"## {release_info.version} ({date:%b %d, %Y})",
            *(
                formatted
                for category in external_categories
                if (formatted := format_entries(category))
            ),
        ]
    )
    internal = format_entries(Category.Internal)

    return Formatted(external=external, internal=internal)


def splice(version: str, existing_contents: str, new_section: str) -> str:
    # Find an existing section for this version, if one exists, to be able to replace it wholesale
    # (NB. we only look at the version number, not the date, for deciding whether the section
    # matches)
    try:
        index_matching = existing_contents.index(f"\n## {version} ")
        search_from_index = index_matching + 1
    except ValueError:
        index_matching = None
        search_from_index = 0

    # Find the next `## 2.minor...` heading, which would be the previous version, to be able to
    # insert/replace the right section, or the end of file, if not such section exists
    try:
        index_previous = existing_contents.index("\n## 2.", search_from_index)
    except ValueError:
        index_previous = len(existing_contents)

    if index_matching is None:
        # if there was no existing section, we're just inserting at that index
        index_matching = index_previous

    return "".join(
        [
            existing_contents[:index_matching],
            "\n",
            new_section,
            "\n",
            existing_contents[index_previous:],
        ]
    )


def splice_into_file(release_info: ReleaseInfo, formatted: Formatted) -> None:
    file_name = release_info.notes_file_name()
    try:
        existing_contents = file_name.read_text()
    except FileNotFoundError:
        # default content if the file doesn't exist yet
        existing_contents = f"# {release_info.slug} Release Series\n"

    file_name.write_text(splice(str(release_info.version), existing_contents, formatted.external))


def update_changelog(release_info: ReleaseInfo) -> Formatted:
    branch_sha = git_fetch(release_info.branch)
    date = datetime.date.today()
    entries = [prepare_sha(sha) for sha in relevant_shas(branch_sha)]

    formatted = format_notes(release_info, entries, date)
    splice_into_file(release_info, formatted)

    return formatted


def update_contributors(release_info: ReleaseInfo) -> None:
    if release_info.branch == "main":
        CONTRIBUTORS_PATH.write_text(
            "Created as part of the release process.\n\n+ "
            + "\n+ ".join(sorted_contributors(git_range="HEAD"))
            + "\n"
        )


def update_version(release_info: ReleaseInfo) -> None:
    if release_info.branch == "main":
        VERSION_PATH.write_text(f"{release_info.version}\n")


def commit_and_pr(release_info: ReleaseInfo, formatted: Formatted, release_manager: str) -> None:
    title = f"Prepare {release_info.version}"
    branch = f"automation/release/{release_info.version}"

    git("checkout", "-b", branch)
    git("add", str(VERSION_PATH), str(CONTRIBUTORS_PATH), str(release_info.notes_file_name()))
    git("commit", "-m", title)
    git("push", "origin", "HEAD")

    github_pr_create(
        base="main",
        head=branch,
        title=title,
        body="\n\n".join([BASE_PR_BODY, formatted.internal]),
        assignee=release_manager,
        labels=["automation:release-prep"],
    )


def main() -> None:
    args = create_parser().parse_args()
    logging.basicConfig(level=args.log_level)

    release_info = ReleaseInfo.determine(args.new)

    formatted = update_changelog(release_info)
    update_contributors(release_info)
    update_version(release_info)
    commit_and_pr(release_info, formatted, args.release_manager)


if __name__ == "__main__":
    main()
