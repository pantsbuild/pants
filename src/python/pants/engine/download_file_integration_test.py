# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.engine.download_file import URLDownloadHandler, download_file
from pants.engine.fs import Digest, DownloadFile, FileDigest, NativeDownloadFile
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks

DOWNLOADS_FILE_DIGEST = FileDigest(
    "8fcbc50cda241aee7238c71e87c27804e7abc60675974eaf6567aa16366bc105", 14
)
DOWNLOADS_EXPECTED_DIRECTORY_DIGEST = Digest(
    "4c9cf91fcd7ba1abbf7f9a0a1c8175556a82bee6a398e34db3284525ac24a3ad", 84
)


def test_no_union_members() -> None:
    union_membership = UnionMembership({})
    digest = run_rule_with_mocks(
        download_file,
        rule_args=[
            DownloadFile("http://pantsbuild.com/file.txt", DOWNLOADS_FILE_DIGEST),
            union_membership,
        ],
        mock_gets=[
            MockGet(
                output_type=Digest,
                input_types=(URLDownloadHandler,),
                mock=lambda _: None,
            ),
            MockGet(
                output_type=Digest,
                input_types=(NativeDownloadFile,),
                mock=lambda _: DOWNLOADS_EXPECTED_DIRECTORY_DIGEST,
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


@pytest.mark.parametrize(
    "scheme, authority, url",
    [
        # Anything (every URL matches)
        (None, None, "s3://pantsbuild.com/file.txt"),
        (None, None, "http://pantsbuild.com/file.txt"),
        (None, None, "http://awesome.pantsbuild.com/file.txt"),
        # Scheme
        ("s3", None, "s3://pantsbuild.com/file.txt"),
        ("http*", None, "http://pantsbuild.com/file.txt"),
        ("http*", None, "https://pantsbuild.com/file.txt"),
        # Authority
        (None, "pantsbuild.com", "s3://pantsbuild.com/file.txt"),
        (None, "pantsbuild.com", "http://pantsbuild.com/file.txt"),
        (None, "pantsbuild.com", "https://pantsbuild.com/file.txt"),
        (None, "*.pantsbuild.com", "https://awesome.pantsbuild.com/file.txt"),
        (None, "*.pantsbuild.com*", "https://awesome.pantsbuild.com/file.txt"),
        (None, "*.pantsbuild.com*", "https://awesome.pantsbuild.com:80/file.txt"),
        # Both
        ("http*", "*.pantsbuild.com", "http://awesome.pantsbuild.com/file.txt"),
    ],
)
def test_matches(scheme, authority, url) -> None:
    class UnionMember(URLDownloadHandler):
        match_scheme = scheme
        match_authority = authority

        def mock_rule(self) -> Digest:
            assert isinstance(self, UnionMember)
            return DOWNLOADS_EXPECTED_DIRECTORY_DIGEST

    union_membership = UnionMembership({URLDownloadHandler: [UnionMember]})

    digest = run_rule_with_mocks(
        download_file,
        rule_args=[
            DownloadFile(url, DOWNLOADS_FILE_DIGEST),
            union_membership,
        ],
        mock_gets=[
            MockGet(
                output_type=Digest,
                input_types=(URLDownloadHandler,),
                mock=UnionMember.mock_rule,
            ),
            MockGet(
                output_type=Digest,
                input_types=(NativeDownloadFile,),
                mock=lambda _: None,
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


@pytest.mark.parametrize(
    "scheme, authority, url",
    [
        # Scheme
        ("s3", None, "http://pantsbuild.com/file.txt"),
        ("s3", None, "as3://pantsbuild.com/file.txt"),
        ("http", None, "https://pantsbuild.com/file.txt"),
        # Authority
        (None, "pantsbuild.com", "http://pantsbuild.com:80/file.txt"),
        (None, "*.pantsbuild.com", "https://pantsbuild.com/file.txt"),
        # Both
        ("http", "*.pantsbuild.com", "https://awesome.pantsbuild.com/file.txt"),
        ("https", "*.pantsbuild.com", "https://pantsbuild.com/file.txt"),
    ],
)
def test_doesnt_match(scheme, authority, url) -> None:
    class UnionMember(URLDownloadHandler):
        match_scheme = scheme
        match_authority = authority

    union_membership = UnionMembership({URLDownloadHandler: [UnionMember]})

    digest = run_rule_with_mocks(
        download_file,
        rule_args=[
            DownloadFile(url, DOWNLOADS_FILE_DIGEST),
            union_membership,
        ],
        mock_gets=[
            MockGet(
                output_type=Digest,
                input_types=(URLDownloadHandler,),
                mock=lambda _: None,
            ),
            MockGet(
                output_type=Digest,
                input_types=(NativeDownloadFile,),
                mock=lambda _: DOWNLOADS_EXPECTED_DIRECTORY_DIGEST,
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_too_many_matches() -> None:
    class AuthorityMatcher(URLDownloadHandler):
        match_authority = "pantsbuild.com"

    class SchemeMatcher(URLDownloadHandler):
        match_scheme = "http"

    union_membership = UnionMembership({URLDownloadHandler: [AuthorityMatcher, SchemeMatcher]})

    with pytest.raises(Exception, match=r"Too many registered URL handlers"):
        run_rule_with_mocks(
            download_file,
            rule_args=[
                DownloadFile("http://pantsbuild.com/file.txt", DOWNLOADS_FILE_DIGEST),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    output_type=Digest,
                    input_types=(URLDownloadHandler,),
                    mock=lambda _: None,
                ),
                MockGet(
                    output_type=Digest,
                    input_types=(NativeDownloadFile,),
                    mock=lambda _: DOWNLOADS_EXPECTED_DIRECTORY_DIGEST,
                ),
            ],
            union_membership=union_membership,
        )
