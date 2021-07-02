# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.util.docutil import DocUrlMatcher, DocUrlRewriter, doc_url, get_title_from_page_content


@pytest.mark.parametrize("slug", ["foo-bar", "baz3", "qux"])
def test_slug_for_url(slug: str) -> None:
    assert DocUrlMatcher().slug_for_url(doc_url(slug)) == slug


def test_slug_for_url_error() -> None:
    with pytest.raises(ValueError) as excinfo:
        DocUrlMatcher().slug_for_url("https://notthedocsite.com/v2.6/foobar")
    assert "Not a docsite URL" in str(excinfo.value)


def test_find_doc_urls() -> None:
    matcher = DocUrlMatcher()
    strs = [
        f"See {doc_url('foo-bar')} for details.",
        f"See {doc_url('qux')}.",  # Don't capture trailing dot.
        f"See {doc_url('foo-bar')} and {doc_url('baz3')}",  # Multiple urls in string.
    ]
    assert matcher.find_doc_urls(strs) == {doc_url(slug) for slug in ["foo-bar", "baz3", "qux"]}


def test_get_title_from_page_content():
    page_content = textwrap.dedent(
        """
      <!DOCTYPE html><html ng-app="hub" lang="en" style="" class=" useReactApp  ">
      <head>
      <script src="blahblah"></script>
      <meta charset="utf-8"><meta http-equiv="X-UA-Compatible" content="IE=edge">
      <title ng-bind="pageTitle">Welcome to Pants!</title>
      <meta name="description" content="Documentation for the Pants v2 build system.">
      </head>
      <body>Welcome to Pants, the ergonomic build system!</body>
    """
    )
    assert get_title_from_page_content(page_content) == "Welcome to Pants!"


def test_doc_url_rewriter():
    dur = DocUrlRewriter(
        {
            "foo": "Foo",
            "bar": "Welcome to Bar!",
        }
    )
    assert dur.rewrite(f"See {doc_url('foo')} for details.") == "See [Foo](doc:foo) for details."
    assert dur.rewrite(f"Check out {doc_url('bar')}.") == "Check out [Welcome to Bar!](doc:bar)."
