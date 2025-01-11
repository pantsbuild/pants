# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Script to fetch external tool versions.

Example:

pants run build-support/bin:external-tool-versions -- --tool pants.backend.k8s.kubectl_subsystem:Kubectl > list.txt
"""

import argparse
import hashlib
import importlib
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from multiprocessing.pool import ThreadPool
from string import Formatter
from urllib.parse import urlparse

import requests

from pants.core.util_rules.external_tool import ExternalToolVersion

logger = logging.getLogger(__name__)


def format_string_to_regex(format_string: str) -> re.Pattern:
    """Converts a format string to a regex.

    >>> format_string_to_regex("/release/v{version}/bin/{platform}/kubectl")
    re.compile('^\\/release\\/v(?P<version>.*)\\/bin\\/(?P<platform>.*)\\/kubectl$')
    """
    result_regex = ["^"]
    parts = Formatter().parse(format_string)
    for literal_text, field_name, format_spec, conversion in parts:
        escaped_text = literal_text.replace("/", r"\/")
        result_regex.append(escaped_text)
        if field_name is not None:
            result_regex.append(rf"(?P<{field_name}>.*)")
    result_regex.append("$")
    return re.compile("".join(result_regex))


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
            yield f"https://cdn.dl.k8s.io/{key}"


def get_k8s_versions(url_template: str, pool: ThreadPool) -> Iterator[str]:
    response = requests.get("https://cdn.dl.k8s.io/", allow_redirects=True)
    urls = _parse_k8s_xml(response.text)
    for v in pool.imap_unordered(fetch_text, urls):
        yield v.strip().lstrip("v")


DOMAIN_TO_VERSIONS_MAPPING: dict[str, Callable[[str, ThreadPool], Iterator[str]]] = {
    # TODO github.com
    "dl.k8s.io": get_k8s_versions,
}


def fetch_version(
    *,
    url_template: str,
    version: str,
    platform: str,
    platform_mapping: dict[str, str],
) -> ExternalToolVersion | None:
    url = url_template.format(version=version, platform=platform_mapping[platform])
    response = requests.get(url, allow_redirects=True)
    if response.status_code != 200:
        logger.error("failed to fetch version: %s\n%s", version, response.text)
        return None

    size = len(response.content)
    sha256 = hashlib.sha256(response.content)
    return ExternalToolVersion(
        version=version,
        platform=platform,
        filesize=size,
        sha256=sha256.hexdigest(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-t",
        "--tool",
        help="Python tool location, for example: pants.backend.tools.taplo.subsystem:Taplo",
        required=True,
    )
    parser.add_argument(
        "--platforms",
        default="macos_arm64,macos_x86_64,linux_arm64,linux_x86_64",
        help="Comma separated list of platforms",
    )
    parser.add_argument(
        "-w",
        "--workers",
        default=16,
        help="Thread pool size",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Verbose output",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    module_string, class_name = args.tool.split(":")
    module = importlib.import_module(module_string)
    cls = getattr(module, class_name)

    platforms = args.platforms.split(",")
    platform_mapping = cls.default_url_platform_mapping

    domain = urlparse(cls.default_url_template).netloc
    get_versions = DOMAIN_TO_VERSIONS_MAPPING[domain]
    pool = ThreadPool(processes=args.workers)
    results = []
    for version in get_versions(cls.default_url_template, pool):
        for platform in platforms:
            logger.debug("fetching version: %s %s", version, platform)
            results.append(
                pool.apply_async(
                    fetch_version,
                    kwds=dict(
                        version=version,
                        platform=platform,
                        url_template=cls.default_url_template,
                        platform_mapping=platform_mapping,
                    ),
                )
            )

    for result in results:
        v = result.get(timeout=60)
        if v is None:
            continue
        print(
            "|".join(
                [
                    v.version,
                    v.platform,
                    v.sha256,
                    str(v.filesize),
                ]
            )
        )


if __name__ == "__main__":
    main()
