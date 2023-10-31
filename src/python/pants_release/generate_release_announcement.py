# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import json
import os

from pants_release.common import VERSION_PATH, sorted_contributors
from pants_release.git import git

from pants.util.dirutil import safe_mkdir
from pants.util.strutil import softwrap

VERSION = VERSION_PATH.read_text().strip()


def announcement_text() -> str:
    cur_version_sha, prev_version_sha = git(
        "log", "-2", "--pretty=format:%h", str(VERSION_PATH)
    ).splitlines(keepends=False)
    git_range = f"{prev_version_sha}..{cur_version_sha}"
    all_contributors = sorted_contributors(git_range)
    new_contributors = sorted(
        [
            line[3:]
            for line in git("diff", git_range, "CONTRIBUTORS.md").splitlines(keepends=False)
            if line.startswith("++ ")
        ]
    )

    announcement = softwrap(
        f"""\
        Pants {VERSION} is now available!

        To upgrade, set `pants_version="{VERSION}"` in the `[GLOBAL]` section of your pants.toml.

        Check the release notes at https://github.com/pantsbuild/pants/releases/tag/release_{VERSION} to see what's new in this release.
        """
    )
    if "dev" in VERSION or "a" in VERSION:
        announcement += "\n\nThanks to all the contributors to this release:\n\n"
        for contributor in all_contributors:
            announcement += contributor
            announcement += "\n"
        if new_contributors:
            announcement += "\nAnd a special shoutout to these first-time contributors:\n\n"
            for contributor in new_contributors:
                announcement += contributor
                announcement += "\n"
            announcement += (
                "\nWelcome to the Pants community! We appreciate your contributions, "
                "and look forward to more of them in the future."
            )
    else:
        announcement += "\n\nThanks to all the contributors to this release!"
    return announcement


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Generate announcement messages into this directory.",
    )
    options = parser.parse_args()
    safe_mkdir(options.output_dir)

    def dump(basename: str, text: str) -> None:
        with open(os.path.join(options.output_dir, basename), "w") as fp:
            fp.write(text)

    announcement = announcement_text()
    dump(
        "slack_announcement.json",
        json.dumps(
            {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": announcement,
                        },
                    },
                ]
            }
        ),
    )
    dump("email_announcement_subject.txt", f"Pants {VERSION} is released")
    dump("email_announcement_body.md", announcement)


if __name__ == "__main__":
    main()
