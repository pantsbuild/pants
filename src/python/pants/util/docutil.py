# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import shutil
from html.parser import HTMLParser
from typing import Iterable, cast

import requests

from pants.version import MAJOR_MINOR


# NB: This is not memoized because that would cause Pants to not pick up terminal resizing when
# using pantsd.
def terminal_width(*, fallback: int = 96, padding: int = 2) -> int:
    return shutil.get_terminal_size(fallback=(fallback, 24)).columns - padding


def doc_url(slug: str) -> str:
    return f"https://www.pantsbuild.org/v{MAJOR_MINOR}/docs/{slug}"


# Code to replace doc urls with appropriate markdown, for rendering on the docsite.

_doc_url_pattern = r"https://www.pantsbuild.org/v(\d+\.[^/]+)/docs/(?P<slug>[a-zA-Z0-9_-]+)"


class DocUrlMatcher:
    """Utilities for regex matching docsite URLs."""

    def __init__(self):
        self._doc_url_re = re.compile(_doc_url_pattern)

    def slug_for_url(self, url: str) -> str:
        mo = self._doc_url_re.match(url)
        if not mo:
            raise ValueError(f"Not a docsite URL: {url}")
        return cast(str, mo.group("slug"))

    def find_doc_urls(self, strs: Iterable[str]) -> set[str]:
        """Find all the docsite urls in the given strings."""
        return {mo.group(0) for s in strs for mo in self._doc_url_re.finditer(s)}


class DocUrlRewriter:
    def __init__(self, slug_to_title: dict[str, str]):
        self._doc_url_re = re.compile(_doc_url_pattern)
        self._slug_to_title = slug_to_title

    def _rewrite_url(self, mo: re.Match) -> str:
        # The docsite injects the version automatically at markdown rendering time, so we
        # must not also do so, or it will be doubled, and the resulting links will be broken.
        slug = mo.group("slug")
        title = self._slug_to_title.get(slug)
        if not title:
            raise ValueError(f"Found empty or no title for {mo.group(0)}")
        return f"[{title}](doc:{slug})"

    def rewrite(self, s: str) -> str:
        return self._doc_url_re.sub(self._rewrite_url, s)


class TitleFinder(HTMLParser):
    """Grabs the page title out of a docsite page."""

    def __init__(self):
        super().__init__()
        self._in_title: bool = False
        self._title: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self._title = data.strip()

    @property
    def title(self) -> str | None:
        return self._title


def get_title_from_page_content(page_content: str) -> str:
    title_finder = TitleFinder()
    title_finder.feed(page_content)
    return title_finder.title or ""


def get_title(url: str) -> str:
    return get_title_from_page_content(requests.get(url).text)


def get_titles(urls: set[str]) -> dict[str, str]:
    """Return map from slug->title for each given docsite URL."""

    matcher = DocUrlMatcher()
    # TODO: Parallelize the http requests.
    #  E.g., by turning generate_docs.py into a plugin goal and using the engine.
    ret = {}
    for url in urls:
        ret[matcher.slug_for_url(url)] = get_title(url)
    return ret
