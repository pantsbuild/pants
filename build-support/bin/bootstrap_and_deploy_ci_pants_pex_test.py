# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from bootstrap_and_deploy_ci_pants_pex import (
    ListingError,
    NonUniqueVersionError,
    _s3_listing_has_unique_version,
)


def test_listing_has_unique_version_no_results() -> None:
    assert not _s3_listing_has_unique_version("prefix", "")
    assert not _s3_listing_has_unique_version("prefix", "{}")


def test_listing_has_unique_version_nominal() -> None:
    assert _s3_listing_has_unique_version(
        "prefix",
        """
        {
            "Versions": [
                {
                    "ETag": "\\"42e2a84a76d7377e5c5a2c5c3e2e2afe\\"",
                    "Size": 207011168,
                    "StorageClass": "STANDARD",
                    "Key": "prefix1",
                    "VersionId": "0_x4c45bLKFS_zOETFrBB7u0HtZWD_j3",
                    "IsLatest": false,
                    "LastModified": "2020-10-11T11:23:32+00:00",
                    "Owner": {
                        "ID": "65a011a29cdf8ec533ec3d1ccaae921c"
                    }
                }
            ]
        }
        """,
    )


def test_listing_has_unique_version_deleted() -> None:
    assert not _s3_listing_has_unique_version(
        "prefix",
        """
        {
            "Versions": [
                {
                    "ETag": "\\"42e2a84a76d7377e5c5a2c5c3e2e2afe\\"",
                    "Size": 207011168,
                    "StorageClass": "STANDARD",
                    "Key": "prefix1",
                    "VersionId": "0_x4c45bLKFS_zOETFrBB7u0HtZWD_j3",
                    "IsLatest": false,
                    "LastModified": "2020-10-11T11:23:32+00:00",
                    "Owner": {
                        "ID": "65a011a29cdf8ec533ec3d1ccaae921c"
                    }
                }
            ],
            "DeleteMarkers": [
                {
                    "Key": "prefix1",
                    "VersionId": "7h5go2iDSRrWPVX8hvDITmWNb0SrHnD_",
                    "IsLatest": true,
                    "LastModified": "2020-11-11T00:00:00+00:00"
                }
            ]
        }
        """,
    )

    assert _s3_listing_has_unique_version(
        "prefix",
        """
        {
            "Versions": [
                {
                    "Key": "prefix1"
                },
                {
                    "Key": "prefix1"
                }
            ],
            "DeleteMarkers": [
                {
                    "Key": "prefix1"
                }
            ]
        }
        """,
    )

    assert not _s3_listing_has_unique_version(
        "prefix",
        """
        {
            "Versions": [
                {
                    "Key": "prefix1"
                },
                {
                    "Key": "prefix1"
                }
            ],
            "DeleteMarkers": [
                {
                    "Key": "prefix1"
                },
                {
                    "Key": "prefix1"
                }
            ]
        }
        """,
    )


def test_listing_has_unique_version_multiple() -> None:
    with pytest.raises(ListingError):
        assert _s3_listing_has_unique_version(
            "prefix",
            """
            {
                "Versions": [
                    {
                        "Key": "prefix1"
                    },
                    {
                        "Key": "prefix2"
                    }
                ]
            }
            """,
        )


def test_listing_has_unique_version_non_unique() -> None:
    with pytest.raises(NonUniqueVersionError):
        assert _s3_listing_has_unique_version(
            "prefix",
            """
            {
                "Versions": [
                    {
                        "Key": "prefix1",
                        "VersionId": "1_x4c45bLKFS_zOETFrBB7u0HtZWD_j3",
                        "LastModified": "2020-10-11T11:23:32+00:00"
                    },
                    {
                        "Key": "prefix1",
                        "VersionId": "0_x4c45bLKFS_zOETFrBB7u0HtZWD_j3",
                        "LastModified": "2020-9-11T11:23:32+00:00"
                    }
                ]
            }
            """,
        )
