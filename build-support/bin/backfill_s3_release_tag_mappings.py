# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import subprocess
from pathlib import Path

from deploy_to_s3 import perform_deploy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--aws-cli-symlink-path",
        help=(
            "The directory (on the $PATH) to symlink the `aws` cli binary into; by default a"
            "standard PATH entry appropriate to the current operating system."
        ),
    )
    options = parser.parse_args()

    tags_deploy_dir = Path("dist/deploy/tags/pantsbuild.pants")
    tags_deploy_dir.mkdir(parents=True, exist_ok=False)

    release_tags = subprocess.run(
        ["git", "tag", "--list", "release_*"], stdout=subprocess.PIPE, text=True, check=True
    ).stdout.splitlines()
    for release_tag in release_tags:
        tag = release_tag.strip()
        commit = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{commit}}"], stdout=subprocess.PIPE, text=True, check=True
        ).stdout.strip()
        (tags_deploy_dir / tag).write_text(commit)

    perform_deploy(aws_cli_symlink_path=options.aws_cli_symlink_path, scope="tags/pantsbuild.pants")


if __name__ == "__main__":
    main()
