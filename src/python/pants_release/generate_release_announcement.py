# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants_release.common import VERSION_PATH, sorted_contributors
from pants_release.git import git

from pants.util.strutil import softwrap


def announcement_text() -> str:
    version = VERSION_PATH.read_text().strip()
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
        Pants {version} is now available!

        To upgrade, set pants_version="{version}" in the [GLOBAL] section of your pants.toml.
        """
    )
    if "dev" in version or "a" in version:
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
                "and look forward to more."
            )
    else:
        announcement += "\n\nThanks to all the contributors to this release!"
    return announcement


if __name__ == "__main__":
    print(announcement_text())
