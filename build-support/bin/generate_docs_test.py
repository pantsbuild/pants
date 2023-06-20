# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest
from generate_docs import DocUrlRewriter, find_doc_urls, get_doc_slug, value_strs_iter

from pants.util.docutil import doc_url


def test_gather_value_strs():
    help_info = {
        "a": "foo",
        "b": ["bar", 5, "baz"],
        "c": 42,
        "d": True,
        "e": {"f": 5, "g": "qux", "h": {"i": "quux"}},
    }
    assert set(value_strs_iter(help_info)) == {"foo", "bar", "baz", "qux", "quux"}


@pytest.mark.parametrize("arg", ["foo-bar", "baz3", "qux#anchor"])
def test_slug_for_url(arg: str) -> None:
    expected_slug = arg.split("#")[0]
    assert get_doc_slug(doc_url(arg)) == expected_slug


def test_slug_for_url_error() -> None:
    with pytest.raises(ValueError) as excinfo:
        get_doc_slug("https://notthedocsite.com/v2.6/foobar")
    assert "Not a docsite URL" in str(excinfo.value)


def test_find_doc_urls() -> None:
    strs = [
        f"See {doc_url('foo-bar')} for details.",
        f"See {doc_url('qux')}.",  # Don't capture trailing dot.
        f"See {doc_url('foo-bar')} and {doc_url('baz3')}",  # Multiple urls in string.
    ]
    assert find_doc_urls(strs) == {doc_url(slug) for slug in ["foo-bar", "baz3", "qux"]}


def test_doc_url_rewriter():
    dur = DocUrlRewriter(
        {
            "foo": "Foo",
            "bar": "Welcome to Bar!",
        }
    )
    assert dur.rewrite(f"See {doc_url('foo')} for details.") == "See [Foo](doc:foo) for details."
    assert (
        dur.rewrite(f"Check out {doc_url('bar#anchor')}.")
        == "Check out [Welcome to Bar!](doc:bar#anchor)."
    )
