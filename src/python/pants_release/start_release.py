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
from pants_release.common import VERSION_PATH
from pants_release.git import git, git_fetch

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the changelog for a release.")
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


def splice(existing_contents: str, new_section: str) -> str:
    # Find the first `## 2.minor...` heading, to be able to insert immediately before it, or the end
    # of file, if not such section exists
    try:
        index = existing_contents.index("\n## 2.")
    except ValueError:
        index = len(existing_contents)
    return "".join([existing_contents[:index], "\n", new_section, "\n", existing_contents[index:]])


def splice_into_file(release_info: ReleaseInfo, formatted: Formatted) -> None:
    file_name = release_info.notes_file_name()
    try:
        existing_contents = file_name.read_text()
    except FileNotFoundError:
        # default content if the file doesn't exist yet
        existing_contents = f"# {release_info.slug} Release Series\n"

    file_name.write_text(splice(existing_contents, formatted.external))


def update_changelog(release_info: ReleaseInfo) -> Formatted:
    branch_sha = git_fetch(release_info.branch)
    date = datetime.date.today()
    entries = [prepare_sha(sha) for sha in relevant_shas(branch_sha)]

    formatted = format_notes(release_info, entries, date)
    splice_into_file(release_info, formatted)

    return formatted


def update_version(release_info: ReleaseInfo) -> None:
    if release_info.branch == "main":
        VERSION_PATH.write_text(f"{release_info.version}\n")


def main() -> None:
    args = create_parser().parse_args()
    release_info = ReleaseInfo.determine(args.new)

    formatted = update_changelog(release_info)
    update_version(release_info)

    print(f"\nCommit {release_info.notes_file_name()} and create a PR.\n\n{formatted.internal}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
