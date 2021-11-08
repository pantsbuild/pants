#!/usr/bin/env python3
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pkgutil
from dataclasses import dataclass

import chevron

"""Generates the custom HTML/CSS block in https://www.pantsbuild.org/docs/who-uses-pants .

To add new companies or make other changes, edit and run this script, then paste the output
into that block instead of its current content. Be sure to check that the page renders properly
and be prepared to revert (via the "Page history" link) if necessary.

On MacOS it's useful to pipe the output of this script into pbcopy, so it's in the clipboard
ready to be pasted:

./pants run build-support/bin/generate_user_list.py | pbcopy

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
    Org(
        "Chartbeat", "https://chartbeat.com/", "https://files.readme.io/861ace7-chartbeat-small.png"
    ),
    Org(
        "Coinbase",
        "https://www.coinbase.com/",
        "https://files.readme.io/a213f0f-coinbase-small.png",
    ),
    Org(
        "ESL Gaming",
        "https://about.eslgaming.com/",
        "https://files.readme.io/b63d33d-esl-small.png",
    ),
    Org(
        "Foursquare",
        "https://foursquare.com/",
        "https://files.readme.io/aa53b52-foursquare-small.png",
    ),
    Org(
        "Grapl",
        "https://www.graplsecurity.com/",
        "https://files.readme.io/8802ffd-grapl-small.png",
    ),
    Org(
        "HousingAnywhere",
        "https://housinganywhere.com/",
        "https://files.readme.io/dd2a703-housinganywhere-small.png",
    ),
    Org("iManage", "https://imanage.com/", "https://files.readme.io/0f7b5f6-imanage-small.png"),
    Org("Ocrolus", "https://www.ocrolus.com/", "https://files.readme.io/ff166fa-ocrolus-small.png"),
    Org(
        "People Data Labs",
        "https://www.peopledatalabs.com/",
        "https://files.readme.io/8c4f5cd-peopledatalabs-small.png",
    ),
    Org(
        "Rippling",
        "https://www.rippling.com/",
        "https://files.readme.io/c8be3a1-rippling-small.png",
    ),
    Org(
        "Snowfall",
        "https://snowfalltravel.com/",
        "https://files.readme.io/13e796f-snowfall-small.png",
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
        orgs.append(Org("", "", ""))
    org_pairs = tuple(OrgPair(orgs[i], orgs[i + 1]) for i in range(0, len(orgs), 2))
    buf = pkgutil.get_data("generate_user_list", "user_list_templates/table.html.mustache")
    print(chevron.render(buf.decode(), context={"org_pairs": org_pairs}))


if __name__ == "__main__":
    main()
