#!/usr/bin/env python3
# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Fetch versions of Terraform and format them for use in known_versions."""

import csv
import itertools
import logging
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional, Tuple, TypeVar
from urllib.parse import urljoin, urlparse

import gnupg
import requests
from bs4 import BeautifulSoup

from pants.backend.terraform.tool import TerraformTool
from pants.core.util_rules.external_tool import ExternalToolVersion

logging.basicConfig(level=logging.INFO)


T = TypeVar("T")


def partition(predicate: Callable[[Any], bool], items: Iterable[T]) -> Tuple[List[T], List[T]]:
    """Split an Iterable into two lists based on a predicate.

    >>> l = [0,1,2,3,4,5,6]
    >>> partition(lambda i: i % 2 == 0, l)
    ([0, 2, 4, 6], [1, 3, 5])
    """
    where_true, where_false = [], []
    for item in items:
        if predicate(item):
            where_true.append(item)
        else:
            where_false.append(item)
    return where_true, where_false


class GPGVerifier:
    """Easily verify GPG signatures."""

    def __init__(self, keydata):
        self.gpg = gnupg.GPG(gnupghome=".")
        import_results = self.gpg.import_keys(keydata)
        if not self.check_import_results(import_results):
            raise ValueError(f"Could not import GPG key, stderr: {import_results.stderr}")

    def validate_signature(self, signatures: bytes, content: bytes) -> gnupg.Verify:
        """Verify GPG signature from the common pattern of a file for the signature and a file for
        the content."""
        with tempfile.NamedTemporaryFile() as signature_file:
            signature_file.write(signatures)
            signature_file.flush()
            verify = self.gpg.verify_data(signature_file.name, content)
        return verify

    @staticmethod
    def check_import_results(import_results: gnupg.ImportResult):
        """Check that our import of the key was successful.

        Looks the import results for one which has an "ok" status. We can't use the number of keys
        imported because a re-import of a key results in 0 keys imported.
        """
        has_ok = any(("ok" in r for r in import_results.results))
        return has_ok


@dataclass(frozen=True)
class Link:
    text: str
    link: str


Links = List[Link]


def get_tf_page(url) -> BeautifulSoup:
    """Get a page from the Terraform website."""
    logging.info(f"fetch url={url}")
    return BeautifulSoup(requests.get(url).text, "html.parser")


def get_tf_links(page: BeautifulSoup) -> Links:
    """Extract the links from a Terraform webpage."""
    items = page.html.body.ul.find_all("li")
    links = [
        Link(li.text.strip(), li.a.get("href"))
        for li in items
        if not li.a.get("href").startswith("..")
    ]
    return links


@dataclass(frozen=True)
class TFVersionLinks:
    platform_links: Links
    sha256sums_link: Link
    signature_link: Link


def get_info_for_version(url) -> TFVersionLinks:
    """Get list of binaries and signatures for a version of Terraform."""
    logging.info(f"getting info for version at {url}")
    all_links = get_tf_links(get_tf_page(url))
    signature_links, platform_links = partition(lambda i: "SHA" in i.link, all_links)

    def link_ends_with(what: str) -> Link:
        return next(filter(lambda s: s.link.endswith(what), signature_links))

    return TFVersionLinks(
        platform_links,
        sha256sums_link=link_ends_with("SHA256SUMS"),
        signature_link=link_ends_with("SHA256SUMS.sig"),
    )


@dataclass(frozen=True)
class VersionHash:
    filename: str
    sha256sum: str


@dataclass(frozen=True)
class VersionHashes:
    sha256sums: List[VersionHash]
    signature: bytes

    def by_file(self) -> Dict[str, str]:
        """Get sha256sum by filename."""
        return {x.filename: x.sha256sum for x in self.sha256sums}


def parse_sha256sums_file(file_text: str) -> List[VersionHash]:
    """Parse Terraform's sha256sums file."""
    return [
        VersionHash(**x)
        for x in csv.DictReader(
            StringIO(file_text),
            delimiter=" ",
            skipinitialspace=True,
            fieldnames=["sha256sum", "filename"],
        )
    ]


def parse_signatures(links: TFVersionLinks, verifier: GPGVerifier) -> VersionHashes:
    """Parse and verify GPG signatures of SHA256SUMs."""

    sha256sums_raw = requests.get(links.sha256sums_link.link)
    sha256sums = parse_sha256sums_file(sha256sums_raw.text)

    signature = requests.get(links.signature_link.link).content

    vr = verifier.validate_signature(signature, sha256sums_raw.content)
    if not vr.valid:
        logging.error(f"signature is not valid for {links.signature_link.text}")
        raise RuntimeError("signature is not valid")
    else:
        logging.info(f"signature is valid for {links.signature_link.text}")

    return VersionHashes(sha256sums, signature)


def get_file_size(url) -> int:
    """Get content-length of a binary."""
    logging.info(f"fetching content-length for {url}")
    r = requests.head(url)
    return int(r.headers["content-length"])


def parse_download_url(url: str) -> Tuple[str, str]:
    """Get the version and platform from the url."""
    filename = Path(urlparse(url).path).stem
    _, version, platform_name, platform_arch = filename.split("_")
    return version, platform_name + "_" + platform_arch


def is_prerelease(version_slug: str) -> bool:
    """Determine if a Terraform version is a prerelease version (alpha, beta, or rc)"""
    return any((x in version_slug for x in {"alpha", "beta", "rc"}))


def fetch_platforms_for_version(
    verifier: GPGVerifier,
    inverse_platform_mapping: Dict[str, str],
    version_slug: str,
    version_links: TFVersionLinks,
) -> Optional[List[ExternalToolVersion]]:
    """Fetch platform binary information for a particular Terraform version."""
    logging.info(
        f"processiong version {version_slug} with {len(version_links.platform_links)} binaries"
    )

    if is_prerelease(version_slug):
        logging.info(f"discarding unsupported prerelease slug={version_slug}")
        return None

    signatures_info = parse_signatures(version_links, verifier)
    sha256sums = signatures_info.by_file()

    out = []

    for platform_link in version_links.platform_links:
        version, platform = parse_download_url(platform_link.link)

        if platform not in inverse_platform_mapping:
            logging.info(f"discarding unsupported platform version={version} platform={platform}")
            continue
        pants_platform = inverse_platform_mapping[platform]

        file_size = get_file_size(platform_link.link)
        sha256sum = sha256sums.get(platform_link.text)
        if not sha256sum:
            logging.warning(f"did not find sha256 sum for version={version} platform={platform}")
            continue

        tool_version = ExternalToolVersion(version, pants_platform, sha256sum, file_size)

        if tool_version:
            logging.info(f"created tool version for version={version} platform={platform}")
            out.append(tool_version)
        else:
            logging.warning(
                f"could not create tool version for version={version} platform={platform}"
            )

    return out


def fetch_versions(
    url: str, verifier: GPGVerifier
) -> Generator[List[ExternalToolVersion], None, None]:
    """Crawl the Terraform version site and identify all supported Terraform binaries."""
    version_page = get_tf_page(url)
    version_links = get_tf_links(version_page)
    platform_version_links = (
        (x.text, get_info_for_version(urljoin(url, x.link))) for x in version_links
    )

    inverse_platform_mapping = {v: k for k, v in TerraformTool.default_url_platform_mapping.items()}

    for version_slug, version_infos in platform_version_links:
        found_versions = fetch_platforms_for_version(
            verifier, inverse_platform_mapping, version_slug, version_infos
        )
        if found_versions:
            yield found_versions


if __name__ == "__main__":
    versions_url = "https://releases.hashicorp.com/terraform/"
    number_of_supported_versions = 23

    keydata = requests.get("https://keybase.io/hashicorp/pgp_keys.asc").content
    verifier = GPGVerifier(keydata)

    versions = itertools.islice(
        fetch_versions(versions_url, verifier), number_of_supported_versions
    )
    print([v.encode() for v in itertools.chain.from_iterable(versions)])
