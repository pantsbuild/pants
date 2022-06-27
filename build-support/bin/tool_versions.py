# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import csv
import logging
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import gnupg  # type: ignore
import requests
from bs4 import BeautifulSoup

from pants.backend.terraform.tool import TerraformTool
from pants.core.util_rules.external_tool import ExternalToolVersion

logging.basicConfig(level=logging.INFO)


def partition(predicate: Callable[[Any], bool], items: Iterable) -> Tuple[List, List]:
    where_true, where_false = [], []
    for item in items:
        if predicate(item):
            where_true.append(item)
        else:
            where_false.append(item)
    return where_true, where_false


class GPGVerifier:
    def __init__(self, keydata):
        self.gpg = gnupg.GPG(gnupghome=".")
        self.gpg.import_keys(keydata)  # TODO: handle import error

    def validate_signature(self, signatures: bytes, content: bytes) -> gnupg.Verify:
        with tempfile.NamedTemporaryFile() as signature_file:
            signature_file.write(signatures)
            signature_file.flush()
            verify = self.gpg.verify_data(signature_file.name, content)
        return verify


@dataclass(frozen=True)
class Link:
    text: str
    link: str


Links = List[Link]


def get_tf_page(url) -> BeautifulSoup:
    return BeautifulSoup(requests.get(url).text, "html.parser")


def get_tf_links(page: BeautifulSoup) -> Links:
    items = page.html.body.ul.find_all("li")
    links = [
        Link(li.text.strip(), li.a.get("href"))
        for li in items
        if not li.a.get("href").startswith("..")
    ]
    return links


@dataclass(frozen=True)
class TFVersionInfo:
    signature_links: Links
    platform_links: Links


def get_platform_info(url) -> TFVersionInfo:
    logging.info(f"get {url}")
    all_links = get_tf_links(get_tf_page(url))
    s, p = partition(lambda i: "SHA" in i.link, all_links)
    return TFVersionInfo(s, p)


def get_file_size(url) -> int:
    r = requests.head(url)
    return int(r.headers["content-length"])


def parse_download_url(url: str) -> Tuple[str, str]:
    """Get the platform from the url."""
    filename = Path(urlparse(url).path).stem
    _, version, platform_name, platform_arch = filename.split("_")
    return version, platform_name + "_" + platform_arch


@dataclass(frozen=True)
class VersionHash:
    filename: str
    sha256sum: str


@dataclass(frozen=True)
class VersionHashes:
    sha256sums: List[VersionHash]
    signature: bytes

    def by_file(self) -> Dict[str, str]:
        return {x.filename: x.sha256sum for x in self.sha256sums}


def parse_signatures(links: Links, verifier: GPGVerifier) -> VersionHashes:
    def link_ends_with(what: str) -> Link:
        return next(filter(lambda s: s.link.endswith(what), links))

    sha256sums_raw = requests.get(link_ends_with("SHA256SUMS").link)
    sha256sums = [
        VersionHash(**x)
        for x in csv.DictReader(
            StringIO(sha256sums_raw.text),
            delimiter=" ",
            skipinitialspace=True,
            fieldnames=["sha256sum", "filename"],
        )
    ]

    signature = requests.get(link_ends_with("SHA256SUMS.sig").link).content

    vr = verifier.validate_signature(signature, sha256sums_raw.content)
    if not vr.valid:
        logging.error(vr.status)
        raise RuntimeError("signature is not valid :(")
    else:
        logging.info("signature is valid :)")

    return VersionHashes(sha256sums, signature)


def make_tool_version(
    version_number, tf_platform, file_size, hash=None
) -> Optional[ExternalToolVersion]:
    inverse_platform_mapping = {v: k for k, v in TerraformTool.default_url_platform_mapping.items()}
    if tf_platform not in inverse_platform_mapping:
        return None
    pants_platform = inverse_platform_mapping[tf_platform]

    return ExternalToolVersion(version_number, pants_platform, hash, file_size)


def fetch_versions(url: str, verifier: GPGVerifier) -> List[ExternalToolVersion]:
    version_page = get_tf_page(url)
    version_links = get_tf_links(version_page)
    platform_version_links = {
        x.text: get_platform_info(urljoin(url, x.link)) for x in version_links[:5]
    }

    out = []
    for version_slug, version_infos in platform_version_links.items():
        logging.info(version_infos.platform_links)
        signatures_info = parse_signatures(version_infos.signature_links, verifier)
        sha256sums = signatures_info.by_file()

        for platform_link in version_infos.platform_links:
            logging.info(f"platform {platform_link.link}")
            file_size = get_file_size(platform_link.link)
            version, platform = parse_download_url(platform_link.link)
            sha256sum = sha256sums.get(platform_link.text)
            tool_version = make_tool_version(version, platform, file_size, sha256sum)
            if tool_version:
                out.append(tool_version)
    return out


if __name__ == "__main__":
    versions_url = "https://releases.hashicorp.com/terraform/"

    keydata = requests.get("https://keybase.io/hashicorp/pgp_keys.asc").content
    verifier = GPGVerifier(keydata)

    versions = fetch_versions(versions_url, verifier)
    print([v.encode() for v in versions])
