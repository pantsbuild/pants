import argparse
import hashlib
from multiprocessing.pool import ThreadPool
import re
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
import importlib
from string import Formatter
from urllib.parse import urlparse

import logging
import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Version:
    version: str
    platform: str


@dataclass(frozen=True)
class VersionHash:
    version: str
    platform: str
    size: int
    sha256: str


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


def get_k8s_versions(url_template: str) -> Iterator[Version]:
    path_template = urlparse(url_template).path
    logger.info("path template: %s", path_template)

    regex = format_string_to_regex(path_template)
    logger.info("path regex: %s", regex)

    response = requests.get("https://cdn.dl.k8s.io/", allow_redirects=True)
    root = ET.fromstring(response.text)
    tag = "{http://doc.s3.amazonaws.com/2006-03-01}"
    for item in root.iter(f"{tag}Contents"):
        key_element = item.find(f"{tag}Key")
        if key_element is None:
            raise RuntimeError("Failed to parse xml, did it change?")

        key = key_element.text
        if match := regex.match(f"/{key}"):
            version = match.group("version")
            platform = match.group("platform")
            yield Version(version=version, platform=platform)


DOMAIN_TO_VERSIONS_MAPPING: dict[str, Callable[[str], Iterator[Version]]] = {
    # TODO github.com
    "dl.k8s.io": get_k8s_versions,
}


def fetch_version(url_template: str, version: Version) -> VersionHash:
    url = url_template.format(version=version.version, platform=version.platform)
    response = requests.get(url)
    size = len(response.content)
    sha256 = hashlib.sha256(response.content)
    return VersionHash(
        version=version.version,
        platform=version.platform,
        size=size,
        sha256=sha256.hexdigest(),
    )


def main():
    logging.basicConfig(level="INFO", format="%(message)s")
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

    args = parser.parse_args()

    module_string, class_name = args.tool.split(":")
    module = importlib.import_module(module_string)
    cls = getattr(module, class_name)

    platforms = args.platforms.split(",")
    mapped_platforms = set(cls.default_url_platform_mapping.get(p) for p in platforms)

    domain = urlparse(cls.default_url_template).netloc
    get_versions = DOMAIN_TO_VERSIONS_MAPPING[domain]
    pool = ThreadPool(processes=args.workers)
    results = []
    for version in get_versions(cls.default_url_template):
        if version.platform not in mapped_platforms:
            continue

        logger.info("fetching version: %s", version)
        results.append(
            pool.apply_async(
                fetch_version,
                args=(cls.default_url_template, version),
            )
        )

    for result in results:
        print(result.get(60))


if __name__ == "__main__":
    main()
