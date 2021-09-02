#!/usr/bin/env python3
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pkgutil
from dataclasses import dataclass

import pystache

"""Generates the custom HTML/CSS block in https://www.pantsbuild.org/docs/who-uses-pants .

To add new companies or make other changes, edit and run this script, then paste the output
into that block instead of its current content. Be sure to check that the page renders properly
and be prepared to revert (via the "Page history" link) if necessary.

NOTE: Please consider adding your company/organization to this list! If you wish to do so then
  thank you, and please follow the guidance at https://pantsbuild.org/register.
"""

# Note: To create an image URL, temporarily add an image block to some page on readme.com (such
#   as the user list page itself), and upload the logo image (after appropriate resizing in GIMP
#   or your tool of choice). Do NOT save the page. Instead, right-click to capture the image URL
#   from the preview in the edit page, and then remove the image block.


@dataclass
class Org:
    name: str
    website: str
    image: str


# Orgs will be displayed in case-insensitive alphabetical order, but it's useful for human readers
# to keep this list in that order too.
_orgs = (
    Org("Chartbeat", "https://chartbeat.com", "https://files.readme.io/d4c9d71-chartbeat.png"),
    Org(
        "ESL Gaming",
        "https://about.eslgaming.com/",
        "https://files.readme.io/b63d33d-esl-small.png",
    ),
    Org("iManage", "https://imanage.com/", "https://files.readme.io/949a4fc-imanage.png"),
    Org(
        "Rippling",
        "https://www.rippling.com/",
        "https://files.readme.io/c8be3a1-rippling-small.png",
    ),
    Org(
        "Snowfall",
        "https://snowfalltravel.com/",
        "https://files.readme.io/62f79c1-snowfall-small.png",
    ),
    Org(
        "Toolchain",
        "https://www.toolchain.com/",
        "https://files.readme.io/43d674d-toolchain_logo_small.png",
    ),
)


@dataclass
class OrgPair:
    a: Org
    b: Org


def main():
    orgs = sorted(list(_orgs), key=lambda x: x.name.lower())
    # Ensure an even number of cells, leaving one to render blankly if necessary.
    if len(orgs) % 2 == 1:
        orgs += Org("", "", "")
    org_pairs = tuple(OrgPair(orgs[i], orgs[i + 1]) for i in range(0, len(orgs), 2))
    buf = pkgutil.get_data("generate_user_list", "user_list_templates/table.html.mustache")
    print(pystache.render(buf.decode(), context={"org_pairs": org_pairs}))


if __name__ == "__main__":
    main()
