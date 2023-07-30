# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants_release.git import github_repo


def main() -> str:
    gh_repo = github_repo()
    releases = gh_repo.get_releases()
    index = "\n".join(
        [
            "<html>",
            "<body>",
            "<h1>Links for Pantsbuild Wheels</h1>",
            *(
                f'<a href="{asset.browser_download_url}">{asset.name}</a>'
                for release in releases
                if release.tag_name.startswith("release_2")
                for asset in release.assets
                if asset.name.endswith(".whl")
            ),
            "</body>",
            "</html>",
        ]
    )
    return index


if __name__ == "__main__":
    print(main())
