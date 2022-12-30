# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
                mock=lambda _: object(),
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


def test_matches_scheme() -> None:
    class UnionMember(URLDownloadHandler):
        match_scheme = "s3"

        def mock_rule(self) -> Digest:
            assert isinstance(self, UnionMember)
            return DOWNLOADS_EXPECTED_DIRECTORY_DIGEST

    union_membership = UnionMembership({URLDownloadHandler: [UnionMember]})

    digest = run_rule_with_mocks(
        download_file,
        rule_args=[
            DownloadFile("s3://pantsbuild.com/file.txt", DOWNLOADS_FILE_DIGEST),
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
                mock=lambda _: object(),
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_matches_authority() -> None:
    class UnionMember(URLDownloadHandler):
        match_authority = "pantsbuild.com"

        def mock_rule(self) -> Digest:
            assert isinstance(self, UnionMember)
            return DOWNLOADS_EXPECTED_DIRECTORY_DIGEST

    union_membership = UnionMembership({URLDownloadHandler: [UnionMember]})

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
                mock=UnionMember.mock_rule,
            ),
            MockGet(
                output_type=Digest,
                input_types=(NativeDownloadFile,),
                mock=lambda _: object(),
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_anything_matcher() -> None:
    class UnionMember(URLDownloadHandler):
        def mock_rule(self) -> Digest:
            assert isinstance(self, UnionMember)
            return DOWNLOADS_EXPECTED_DIRECTORY_DIGEST

    union_membership = UnionMembership({URLDownloadHandler: [UnionMember]})

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
                mock=UnionMember.mock_rule,
            ),
            MockGet(
                output_type=Digest,
                input_types=(NativeDownloadFile,),
                mock=lambda _: object(),
            ),
        ],
        union_membership=union_membership,
    )
    assert digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_doesnt_match() -> None:
    class AuthorityMatcher(URLDownloadHandler):
        match_authority = "awesome.pantsbuild.com"

    class SchemeMatcher(URLDownloadHandler):
        match_scheme = "s3"

    union_membership = UnionMembership({URLDownloadHandler: [AuthorityMatcher, SchemeMatcher]})

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
                mock=lambda _: object(),
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
