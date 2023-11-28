#!/usr/bin/env python3
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
    image: str | None


# Orgs will be displayed in case-insensitive alphabetical order, but it's useful for human readers
# to keep this list in that order too.
_orgs = (
    Org("Aiven", "https://aiven.io/", "https://files.readme.io/20085f3-aiven-small.png"),
    Org(
        "Astranis",
        "https://www.astranis.com/",
        "https://files.readme.io/e4989d4-astranis-small.png",
    ),
    Org(
        "Aviva Credito",
        "https://www.avivacredito.com/",
        "https://files.readme.io/dfc2801-aviva.png",
    ),
    Org("Brand24", "https://brand24.com/", "https://files.readme.io/e3203d1-brand24-small.png"),
    Org(
        "Chartbeat", "https://chartbeat.com/", "https://files.readme.io/861ace7-chartbeat-small.png"
    ),
    Org(
        "Coinbase",
        "https://www.coinbase.com/",
        "https://files.readme.io/a213f0f-coinbase-small.png",
    ),
    Org(
        "Doctrine",
        "https://www.doctrine.fr/",
        "https://files.readme.io/8497e9c-doctrine-small.png",
    ),
    Org(
        "Embark Studios",
        "https://www.embark-studios.com/",
        "https://files.readme.io/6ed9278-embark-small.png",
    ),
    Org(
        "ESL Gaming",
        "https://about.eslgaming.com/",
        "https://files.readme.io/b63d33d-esl-small.png",
    ),
    Org(
        "ExoFlare",
        "https://www.exoflare.com/open-source/?utm_source=pants&utm_campaign=open_source",
        "https://files.readme.io/31bb960-exoflare-small.png",
    ),
    Org(
        "Foursquare",
        "https://foursquare.com/",
        "https://files.readme.io/aa53b52-foursquare-small.png",
    ),
    Org(
        "Geminus",
        "https://www.geminus.ai/",
        "https://files.readme.io/0da3c3f-geminus-small.png",
    ),
    Org("Grapl", "https://www.graplsecurity.com/", "https://files.readme.io/341b9cd-grapl.png"),
    Org(
        "HousingAnywhere",
        "https://housinganywhere.com/",
        "https://files.readme.io/dd2a703-housinganywhere-small.png",
    ),
    Org("IBM", "https://www.ibm.com/", None),
    Org("iManage", "https://imanage.com/", "https://files.readme.io/0f7b5f6-imanage-small.png"),
    Org("Kaiko", "https://www.kaiko.ai/", "https://files.readme.io/069b55d-kaiko.png"),
    Org("Lablup", "https://lablup.com/", "https://files.readme.io/a94d375-lablup-small.png"),
    Org("Myst AI", "https://www.myst.ai/", "https://files.readme.io/802d8fa-myst_ai_small.png"),
    Org("Ocrolus", "https://www.ocrolus.com/", "https://files.readme.io/ff166fa-ocrolus-small.png"),
    Org(
        "Orca Security",
        "https://orca.security/",
        "https://files.readme.io/e87f6c5-Orca_Security-small.png",
    ),
    Org("Pave", "https://www.pave.dev/", "https://files.readme.io/924aa3e-pave-small.png"),
    Org("Payhere", "https://payhere.in/", "https://files.readme.io/d263cfd-payhere-small.jpg"),
    Org(
        "People Data Labs",
        "https://www.peopledatalabs.com/",
        "https://files.readme.io/8c4f5cd-peopledatalabs-small.png",
    ),
    Org("Ponder", "https://ponder.io/", "https://files.readme.io/fd34269-ponder.png"),
    Org(
        "Rippling",
        "https://www.rippling.com/",
        "https://files.readme.io/c8be3a1-rippling-small.png",
    ),
    Org(
        "Salesforce",
        "https://salesforce.com/",
        "https://files.readme.io/d902211-small-salesforce-logo-small.png",
    ),
    Org(
        "Snowfall",
        "https://snowfalltravel.com/",
        "https://files.readme.io/245f03e-snowfall-small.png",
    ),
    Org(
        "Tessian",
        "https://www.tessian.com",
        "https://files.readme.io/6ef9d57-tessian-small.png",
    ),
    Org("Unit", "https://unit.co", "https://files.readme.io/eda8106-unit.png"),
    Org("Valon", "https://valon.com/", "https://files.readme.io/df5216a-valon-small.png"),
    Org(
        "Vicara Solutions",
        "https://vicarasolutions.com/",
        "https://files.readme.io/1748a22-vicara-solutions.png",
    ),
    Org("Whisper", "https://whisper.ai/", "https://files.readme.io/cd60b22-whisper.png"),
)


@dataclass
class OrgPair:
    a: Org
    b: Org


def main():
    orgs = sorted(_orgs, key=lambda x: x.name.lower())
    # Ensure an even number of cells, leaving one to render blankly if necessary.
    if len(orgs) % 2 == 1:
        orgs.append(Org("", "", ""))
    org_pairs = tuple(OrgPair(orgs[i], orgs[i + 1]) for i in range(0, len(orgs), 2))
    buf = pkgutil.get_data("generate_user_list", "user_list_templates/table.html.mustache")
    print(chevron.render(buf.decode(), data={"org_pairs": org_pairs}))


if __name__ == "__main__":
    main()
