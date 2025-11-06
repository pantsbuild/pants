# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Generator, Iterable

import aiohttp
import aiohttp_retry
from aiohttp.http import SERVER_SOFTWARE as DEFAULT_USER_AGENT
from aiohttp_retry.types import ClientType
from bs4 import BeautifulSoup

# When adding distros to this map, make sure to add them to:
# ..target_types.DebDistroField.valid_choices
DISTRO_PACKAGE_SEARCH_URL = {
    "debian": "https://packages.debian.org/search",
    "ubuntu": "https://packages.ubuntu.com/search",
}


async def deb_search_for_sonames(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: Iterable[str],
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, dict[str, list[str]]]:
    """Given a soname, lookup the deb package that provides it.

    Tools like 'apt-get -S' and 'apt-file' only work for the host's active distro and distro
    version. This code, however, should be able to run on any host even non-debian and non-ubuntu
    hosts. So, it uses an API call instead of local tooling.
    """
    search_url = DISTRO_PACKAGE_SEARCH_URL[distro]

    # tasks are IO bound
    async with (
        aiohttp_retry.RetryClient(
            retry_options=aiohttp_retry.JitterRetry(attempts=5),
            headers={aiohttp.hdrs.USER_AGENT: user_agent},
            # version=aiohttp.HttpVersion11,  # aiohttp does not support HTTP/2 (waiting for contribution)
            # timeout=aiohttp.ClientTimeout(total=5 * 60, sock_connect=30),
        ) as client,
        asyncio.TaskGroup() as tg,  # client must be before tg in this async with block
    ):
        tasks = {
            soname: tg.create_task(
                deb_search_for_soname(client, search_url, distro_codename, debian_arch, soname)
            )
            for soname in sonames
        }

    # result parsing is CPU bound
    packages: defaultdict[str, dict[str, list[str]]] = defaultdict(dict)
    for soname, task in tasks.items():
        html_doc = task.result()
        for so_file, so_packages in deb_packages_from_html_response(html_doc):
            packages[soname][so_file] = list(
                so_packages
            )  # list makes json serialization more predicatable

    return dict(packages)


async def deb_search_for_soname(
    http: ClientType,
    search_url: str,
    distro_codename: str,
    debian_arch: str,
    soname: str,
) -> str:
    """Use API to search for deb packages that contain soname.

    This HTTP+HTML package search API, sadly, does not support any format other than HTML (not JSON,
    YAML, etc).
    """
    # https://salsa.debian.org/webmaster-team/packages/-/blob/master/SEARCHES?ref_type=heads#L110-136
    query_params = {
        "format": "html",  # sadly, this API only supports format=html.
        "searchon": "contents",
        "mode": "exactfilename",  # soname should be exact filename.
        # mode=="" means find files where `filepath.endswith(keyword)`
        # mode=="filename" means find files where `keyword in filename`
        # mode=="exactfilename" means find files where `filename==keyword`
        "arch": debian_arch,
        "suite": distro_codename,
        "keywords": soname,
    }

    async with http.get(search_url, params=query_params) as response:
        # response.status is 200 even if there was an error (like bad distro_codename),
        # unless the service is unavailable which happens somewhat frequently.
        response.raise_for_status()  # That was the last retry. Give up and alert the user.

        # sadly the "API" returns html and does not support other formats.
        html_doc = await response.text()

    return html_doc


def deb_packages_from_html_response(
    html_doc: str,
) -> Generator[tuple[str, tuple[str, ...]]]:
    """Extract deb packages from an HTML search response.

    This uses beautifulsoup to parse the search API's HTML responses with logic that is very similar
    to the MIT licensed apt-search CLI tool. This does not use apt-search directly because it is not
    meant to be a library, and it hardcodes the ubuntu package search URL. https://github.com/david-
    haerer/apt-search
    """

    # inspiration from (MIT licensed):
    # https://github.com/david-haerer/apt-search/blob/main/apt_search/main.py
    # (this script handles more API edge cases than apt-search and creates structured data)

    soup = BeautifulSoup(html_doc, "html.parser")

    # .table means 'search for a <table> tag'. The response should only have one.
    # In xmlpath, descending would look like one of these:
    #   /html/body/div[1]/div[3]/div[2]/table
    #   /html/body/div[@id="wrapper"]/div[@id="content"]/div[@id="pcontentsres"]/table
    results_table = soup.table

    if results_table is None:
        # No package(s) found
        return

    # results_table is basically (nb: " [amd64] " is only present for arch=any and packages can be a list):
    #   <table>
    #     <tr><th>File</th><th>Packages</th></tr>
    #     <tr>
    #       <td class="file">/usr/lib/x86_64-linux-gnu/<span class="keyword">libldap-2.5.so.0</span></td>
    #       <td><a href="...">libldap-2.5.0</a> [amd64] </td>
    #     </tr>
    #     <tr>
    #       <td class="file">/usr/sbin/<span class="keyword">dnsmasq</span></td>
    #       <td><a href="...">dnsmasq-base</a>, <a href="...">dnsmasq-base-lua</a></td>
    #     </tr>
    #   </table>
    # But, html is semi-structured, so assume that it can be in a broken state.

    for row in results_table.find_all("tr"):
        cells = tuple(row.find_all("td"))
        if len(cells) < 2:
            # ignore malformed rows with missing cell(s).
            continue
        file_cell, pkgs_cell = cells[:2]
        file_text = file_cell.get_text(strip=True)
        packages = [pkg_a.get_text(strip=True) for pkg_a in pkgs_cell.find_all("a")]
        yield file_text, tuple(packages)

    return


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--user-agent-suffix")
    arg_parser.add_argument(
        "--distro", default="ubuntu", choices=tuple(DISTRO_PACKAGE_SEARCH_URL.keys())
    )
    arg_parser.add_argument("--distro-codename", required=True)
    arg_parser.add_argument("--arch", default="amd64")
    arg_parser.add_argument("sonames", nargs="+")
    options = arg_parser.parse_args()

    user_agent_suffix = options.user_agent_suffix
    user_agent = (
        DEFAULT_USER_AGENT if not user_agent_suffix else f"{DEFAULT_USER_AGENT} {user_agent_suffix}"
    )

    packages = asyncio.get_event_loop().run_until_complete(
        deb_search_for_sonames(
            distro=options.distro,
            distro_codename=options.distro_codename,
            debian_arch=options.arch,
            sonames=tuple(options.sonames),
            user_agent=user_agent,
        )
    )

    if not packages:
        print("{}")
        print(
            f"No {options.distro} {options.distro_codename} ({options.arch}) packages"
            f" found for sonames: {options.sonames}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(packages, indent=None, separators=(",", ":")))

    return 0


if __name__ == "__main__":
    sys.exit(main())
