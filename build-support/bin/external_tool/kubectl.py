# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from multiprocessing.pool import ThreadPool

import requests


def fetch_text(url: str) -> str:
    response = requests.get(url)
    return response.text


def _parse_k8s_xml(text: str) -> Iterator[str]:
    regex = re.compile(r"release\/stable-(?P<version>[0-9\.]+).txt")
    root = ET.fromstring(text)
    tag = "{http://doc.s3.amazonaws.com/2006-03-01}"
    for item in root.iter(f"{tag}Contents"):
        key_element = item.find(f"{tag}Key")
        if key_element is None:
            raise RuntimeError("Failed to parse xml, did it change?")

        key = key_element.text
        if key and regex.match(key):
            yield f"https://dl.k8s.io/{key}"


class KubernetesReleases:
    def __init__(self, pool: ThreadPool, only_latest: bool) -> None:
        self.only_latest = only_latest
        self.pool = pool

    def get_releases(self, url_template: str) -> Iterator[str]:
        urls: Iterator[str]
        if self.only_latest:
            urls = iter(("https://dl.k8s.io/release/stable.txt",))
        else:
            response = requests.get("https://dl.k8s.io/", allow_redirects=True)
            urls = _parse_k8s_xml(response.text)

        for v in self.pool.imap_unordered(fetch_text, urls):
            yield v.strip()
