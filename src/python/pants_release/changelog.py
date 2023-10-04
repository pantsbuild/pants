#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

import github
from pants_release.common import die
from pants_release.git import git, github_repo

logger = logging.getLogger(__name__)


def relevant_shas(tag: str) -> list[str]:
    try:
        prior_tag = git("describe", "--tags", "--abbrev=0", f"{tag}~1")
    except subprocess.CalledProcessError:
        die("Ensure that you have the full history of the relevant branch locally.")
    print(f"Found prior tag: {prior_tag}", file=sys.stderr)
    return git("log", "--format=format:%H", tag, f"^{prior_tag}").splitlines()


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


def categorize(pr_num: str, repo: github.Repository.Repository) -> Category | None:
    print(f"Categorizing PR #{pr_num}... ", file=sys.stderr)

    def complete_categorization(category: Category | str) -> Category | None:
        print(f"{category}", file=sys.stderr)
        return category if isinstance(category, Category) else None

    pull = repo.get_pull(int(pr_num))
    for label in pull.labels:
        name = label.name
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


def prepare_sha(sha: str, repo: github.Repository.Repository) -> Entry:
    subject = git("log", "-1", "--format=format:%s", sha)
    pr_num_match = re.search(r"\(#(\d{4,5})\)\s*$", subject)
    if not pr_num_match:
        return Entry(category=None, text=f"* {subject}")
    pr_num = pr_num_match.groups()[0]
    category = categorize(pr_num, repo)
    pr_url = f"https://github.com/pantsbuild/pants/pull/{pr_num}"
    subject_with_url = subject.replace(f"(#{pr_num})", f"([#{pr_num}]({pr_url}))")
    return Entry(category=category, text=f"* {subject_with_url}")


def format_notes(entries: list[Entry]) -> str:
    entries_by_category = defaultdict(list)
    for entry in entries:
        entries_by_category[entry.category].append(entry.text)

    def format_entries(category: Category | None) -> str:
        entries = entries_by_category.get(category, [])
        heading = category.heading() if category else "Uncategorized"
        lines = "\n\n".join(entries)
        if not entries:
            return ""
        return f"## {heading}\n\n{lines}"

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

    notes = "\n\n".join(
        formatted for category in external_categories if (formatted := format_entries(category))
    )

    return notes


def main(tag) -> None:
    repo = github_repo()

    # NB: This assumes the tag (and relevant history) is already pulled
    entries = [prepare_sha(sha, repo) for sha in relevant_shas(tag)]
    notes = format_notes(entries)

    print(notes)


if __name__ == "__main__":
    main(sys.argv[1])
