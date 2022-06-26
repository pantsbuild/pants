# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# from pants.core.util_rules.external_tool import ExternalToolVersion
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


versions_url = "https://releases.hashicorp.com/terraform/"


@dataclass(frozen=True)
class Link:
    text: str
    link: str


Links = Dict[str, str]


def get_tf_page(url) -> BeautifulSoup:
    return BeautifulSoup(requests.get(url).text, "html.parser")


def get_tf_links(page: BeautifulSoup) -> Links:
    items = page.html.body.ul.find_all("li")
    links = {
        li.text.strip(): li.a.get("href") for li in items if not li.a.get("href").startswith("..")
    }
    return links


@dataclass(frozen=True)
class TFVersionInfo:
    signature_links: Links
    platform_links: Links


def get_platform_info(base_url: str, slug: str) -> TFVersionInfo:
    url = urljoin(base_url, slug)
    logging.info(f"get {url}")
    all_links = get_tf_links(get_tf_page(url))
    s, p = partition(lambda i: "SHA" in i[1], all_links.items())

    return TFVersionInfo(dict(s), dict(p))


def get_file_size(url) -> int:
    r = requests.head(url)
    return int(r.headers["content-length"])


def parse_download_url(url: str) -> Tuple[str, str]:
    """Get the platform from the url."""
    filename = Path(urlparse(url).path).stem
    _, version, platform_name, platform_arch = filename.split("_")
    return version, platform_name + "_" + platform_arch


def make_tool_version(
    version_number, tf_platform, file_size, hash=None
) -> Optional[ExternalToolVersion]:
    inverse_platform_mapping = {v: k for k, v in TerraformTool.default_url_platform_mapping.items()}
    if tf_platform not in inverse_platform_mapping:
        return None
    pants_platform = inverse_platform_mapping[tf_platform]

    return ExternalToolVersion(version_number, pants_platform, hash, file_size)


def fetch_versions(url: str) -> List["ExternalToolVersion"]:
    version_page = get_tf_page(url)
    version_links = get_tf_links(version_page)
    platform_version_links = {
        version_number: get_platform_info(url, link)
        for version_number, link in list(version_links.items())[:5]
    }
    out = []
    for version_slug, version_infos in platform_version_links.items():
        logging.info(version_infos.platform_links)
        for n, platform_link in version_infos.platform_links.items():
            logging.info(f"platform {platform_link}")
            file_size = get_file_size(platform_link)
            version, platform = parse_download_url(platform_link)
            tool_version = make_tool_version(version, platform, file_size, None)
            if tool_version:
                out.append(tool_version)
    print(out)
    return out


if __name__ == "__main__":
    fetch_versions(versions_url)
