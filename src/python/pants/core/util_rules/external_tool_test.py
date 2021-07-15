# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from contextlib import contextmanager

import pytest

from pants.core.util_rules.external_tool import (
    ExternalTool,
    ExternalToolError,
    ExternalToolRequest,
    TemplatedExternalTool,
    UnknownVersion,
    UnsupportedVersion,
    UnsupportedVersionUsage,
)
from pants.engine.fs import DownloadFile, FileDigest
from pants.engine.platform import Platform
from pants.testutil.option_util import create_subsystem


class FooBar(ExternalTool):
    name = "foobar"
    options_scope = "foobar"
    default_version = "3.4.7"
    default_known_versions = [
        "3.2.0|darwin   |1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "3.2.0|linux_ppc|39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux    |c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.4.7|darwin   |9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.4.7|linux    |a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
    ]

    def generate_url(self, plat: Platform) -> str:
        if plat == Platform.darwin:
            plat_str = "osx-x86_64"
        elif plat == Platform.linux:
            plat_str = "linux-x86_64"
        else:
            raise ExternalToolError()
        return f"https://foobar.org/bin/v{self.version}/foobar-{self.version}-{plat_str}.tgz"

    def generate_exe(self, plat: Platform) -> str:
        return f"foobar-{self.version}/bin/foobar"


class TemplatedFooBar(TemplatedExternalTool):
    name = "foobar"
    options_scope = "foobar"
    default_version = "3.4.7"
    default_known_versions = [
        "3.2.0|darwin   |1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "3.2.0|linux_ppc|39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux    |c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.4.7|darwin   |9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.4.7|linux    |a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
    ]
    default_url_template = "https://foobar.org/bin/v{version}/foobar-{version}-{platform}.tgz"
    default_url_platform_mapping = {
        "darwin": "osx-x86_64",
        "linux": "linux-x86_64",
    }

    def generate_exe(self, plat: Platform) -> str:
        return f"foobar-{self.version}/bin/foobar"


def test_generate_request() -> None:
    def do_test(
        expected_url: str, expected_length: int, expected_sha256: str, plat: Platform, version: str
    ) -> None:
        foobar = create_subsystem(
            FooBar,
            version=version,
            known_versions=FooBar.default_known_versions,
        )
        templated_foobar = create_subsystem(
            TemplatedFooBar,
            version=version,
            known_versions=TemplatedFooBar.default_known_versions,
            url_template=TemplatedFooBar.default_url_template,
            url_platform_mapping=TemplatedFooBar.default_url_platform_mapping,
        )
        expected = ExternalToolRequest(
            DownloadFile(
                url=expected_url, expected_digest=FileDigest(expected_sha256, expected_length)
            ),
            f"foobar-{version}/bin/foobar",
        )
        assert expected == foobar.get_request(plat)
        assert expected == templated_foobar.get_request(plat)

    do_test(
        "https://foobar.org/bin/v3.2.0/foobar-3.2.0-osx-x86_64.tgz",
        123346,
        "1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8",
        Platform.darwin,
        "3.2.0",
    )
    do_test(
        "https://foobar.org/bin/v3.4.7/foobar-3.4.7-linux-x86_64.tgz",
        134213,
        "a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5",
        Platform.linux,
        "3.4.7",
    )

    with pytest.raises(UnknownVersion):
        create_subsystem(
            FooBar, version="9.9.9", known_versions=FooBar.default_known_versions
        ).get_request(Platform.darwin)


class ConstrainedTool(TemplatedExternalTool):
    name = "foobar"
    options_scope = "foobar"
    version_constraints = ">3.2.1, <3.8"
    default_version = "v3.4.7"
    default_known_versions = [
        "v3.2.0|darwin   |1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "v3.2.0|linux_ppc|39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "v3.2.0|linux    |c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "v3.4.7|darwin   |9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "v3.4.7|linux    |a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
    ]
    default_url_template = "https://foobar.org/bin/v{version}/foobar-{version}-{platform}.tgz"
    default_url_platform_mapping = {
        "darwin": "osx-x86_64",
        "linux": "linux-x86_64",
    }

    def generate_exe(self, plat: Platform) -> str:
        return f"foobar-{self.version}/bin/foobar"


@contextmanager
def no_exception():
    yield None


@pytest.mark.parametrize(
    "version, action, assert_expectation, expect_logged",
    [
        (
            "v1.2.3",
            UnsupportedVersionUsage.RaiseError,
            pytest.raises(
                UnsupportedVersion,
                match="foobar v1.2.3 does not satisfy the version constraints foobar<3.8,>3.2.1",
            ),
            None,
        ),
        (
            "v3.2.2",
            UnsupportedVersionUsage.RaiseError,
            pytest.raises(
                UnknownVersion, match="No known version of foobar v3.2.2 for darwin found in"
            ),
            None,
        ),
        (
            "v3.4.7",
            UnsupportedVersionUsage.RaiseError,
            no_exception(),
            None,
        ),
        (
            "v3.8.0",
            UnsupportedVersionUsage.RaiseError,
            pytest.raises(
                UnsupportedVersion, match="foobar v3.8.0 does not satisfy the version constraints"
            ),
            None,
        ),
        (
            "v3.8.0",
            UnsupportedVersionUsage.LogWarning,
            pytest.raises(
                UnknownVersion, match="No known version of foobar v3.8.0 for darwin found in"
            ),
            [
                (
                    logging.WARNING,
                    "foobar v3.8.0 may not be compatible with this version of pants, as it does not satisfy the constraints foobar<3.8,>3.2.1",
                )
            ],
        ),
        (
            "v3.8.0",
            UnsupportedVersionUsage.Allow,
            pytest.raises(
                UnknownVersion, match="No known version of foobar v3.8.0 for darwin found in"
            ),
            [
                (
                    logging.DEBUG,
                    "Ignoring constraints for version v3.8.0, does not satisfy version constraints foobar<3.8,>3.2.1",
                )
            ],
        ),
    ],
)
def test_version_constraints(caplog, version, action, assert_expectation, expect_logged) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    with assert_expectation:
        create_subsystem(
            ConstrainedTool,
            version=version,
            use_unsupported_version=action,
            known_versions=ConstrainedTool.default_known_versions,
            url_template=ConstrainedTool.default_url_template,
            url_platform_mapping=ConstrainedTool.default_url_platform_mapping,
        ).get_request(Platform.darwin)

    if expect_logged:
        assert len(caplog.records) == len(expect_logged)
        for idx, (lvl, msg) in enumerate(expect_logged):
            log_record = caplog.records[idx]
            assert msg in log_record.message
            assert lvl == log_record.levelno
    else:
        assert not caplog.records
