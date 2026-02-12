# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import re

import pytest

from pants.core.goals.export import ExportedBinary, ExportRequest
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExportExternalToolRequest,
    ExternalTool,
    ExternalToolError,
    ExternalToolRequest,
    MaybeExportResult,
    TemplatedExternalTool,
    UnknownVersion,
    UnsupportedVersion,
    UnsupportedVersionUsage,
    _ExportExternalToolForResolveRequest,
    export_external_tool,
)
from pants.engine.fs import CreateDigest, DigestContents, DownloadFile, FileContent, FileDigest
from pants.engine.internals.native_engine import Digest
from pants.engine.platform import Platform
from pants.engine.rules import QueryRule
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.scope import Scope, ScopedOptions
from pants.testutil.option_util import create_subsystem
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import RuleRunner, run_rule_with_mocks
from pants.util.strutil import softwrap


class FooBar(ExternalTool):
    name = "foobar"
    options_scope = "foobar"
    default_version = "3.4.7"
    default_known_versions = [
        "3.2.0|macos_x86_64|1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "3.2.0|linux_ppc   |39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux_x86_64|c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.4.7|macos_x86_64|9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.4.7|linux_x86_64|a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
        "3.4.7|macos_arm64 |aca5c1da0192e2fd46b7b55ab290a92c5f07309e7b0ebf4e45ba95731ae98291|145678|https://macfoo.org/bin/v3.4.7/mac-m1-v3.4.7.tgz",
    ]

    def generate_url(self, plat: Platform) -> str:
        if plat == Platform.macos_x86_64:
            plat_str = "osx-x86_64"
        elif plat == Platform.linux_x86_64:
            plat_str = "linux-x86_64"
        elif plat == Platform.macos_arm64:
            plat_str = "osx-aarch64"
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
        "3.4.7|linux_x86_64|a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
        "3.4.7|macos_arm64 |aca5c1da0192e2fd46b7b55ab290a92c5f07309e7b0ebf4e45ba95731ae98291|145678|https://macfoo.org/bin/v3.4.7/mac-m1-v3.4.7.tgz",
        "3.4.7|macos_x86_64|9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.2.0|linux_ppc   |39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux_x86_64|c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.2.0|macos_x86_64|1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
    ]
    default_url_template = "https://foobar.org/bin/v{version}/foobar-{version}-{platform}.tgz"
    default_url_platform_mapping = {
        "macos_x86_64": "osx-x86_64",
        "macos_arm64": "osx-aarch64",
        "linux_x86_64": "linux-x86_64",
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
        Platform.macos_x86_64,
        "3.2.0",
    )
    do_test(
        "https://foobar.org/bin/v3.4.7/foobar-3.4.7-linux-x86_64.tgz",
        134213,
        "a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5",
        Platform.linux_x86_64,
        "3.4.7",
    )
    do_test(
        "https://macfoo.org/bin/v3.4.7/mac-m1-v3.4.7.tgz",
        145678,
        "aca5c1da0192e2fd46b7b55ab290a92c5f07309e7b0ebf4e45ba95731ae98291",
        Platform.macos_arm64,
        "3.4.7",
    )

    with pytest.raises(UnknownVersion):
        create_subsystem(
            FooBar, version="9.9.9", known_versions=FooBar.default_known_versions
        ).get_request(Platform.macos_x86_64)


@pytest.fixture
def rule_runner():
    return RuleRunner(
        rules=[QueryRule(ScopedOptions, (Scope,)), *external_tool.rules()],
    )


def test_export(rule_runner) -> None:
    """Tests export_external_tool.

    Ensures we locate the class and prepare the Digest correctly
    """
    platform = Platform.linux_x86_64
    union_membership = UnionMembership.from_rules(
        {
            UnionRule(ExportRequest, ExportExternalToolRequest),
            UnionRule(ExportableTool, TemplatedFooBar),
        }
    )

    templated_foobar = create_subsystem(
        TemplatedFooBar,
        version=TemplatedFooBar.default_version,
        known_versions=TemplatedFooBar.default_known_versions,
        url_template=TemplatedFooBar.default_url_template,
        url_platform_mapping=TemplatedFooBar.default_url_platform_mapping,
    )

    def fake_get_options(scope) -> ScopedOptions:
        """Copy the options from the instantiated tool."""
        assert scope.scope == "foobar"
        return ScopedOptions(
            Scope("foobar"),
            templated_foobar.options,
        )

    def fake_download(_) -> DownloadedExternalTool:
        exe = templated_foobar.generate_exe(platform)
        digest = rule_runner.request(
            Digest,
            (
                CreateDigest(
                    [
                        FileContent(exe, b"exe"),
                        FileContent(
                            "readme.md", b"another file that would conflict if exported to `bin`"
                        ),
                    ]
                ),
            ),
        )

        return DownloadedExternalTool(digest, exe)

    result: MaybeExportResult = run_rule_with_mocks(
        export_external_tool,
        rule_args=[_ExportExternalToolForResolveRequest("foobar"), platform, union_membership],
        mock_calls={
            "pants.engine.internals.options_parsing.scope_options": fake_get_options,
            "pants.core.util_rules.external_tool.download_external_tool": fake_download,
        },
        union_membership=union_membership,
    )

    assert result.result is not None, "failed to export anything at all"

    exported = result.result
    assert exported.exported_binaries == (ExportedBinary("foobar", "foobar-3.4.7/bin/foobar"),), (
        "didn't request exporting correct bin"
    )

    exported_digest: DigestContents = rule_runner.request(DigestContents, (exported.digest,))
    assert len(exported_digest) == 2, "digest didn't contain all files"

    exported_files = {e.path: e.content for e in exported_digest}
    assert exported_files["foobar-3.4.7/bin/foobar"] == b"exe", (
        "digest didn't export our executable"
    )


class ConstrainedTool(TemplatedExternalTool):
    name = "foobar"
    options_scope = "foobar"
    version_constraints = ">3.2.1, <3.8"
    default_version = "v3.4.7"
    default_known_versions = [
        "v3.4.7|linux_x86_64|a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
        "v3.4.7|macos_x86_64|9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "v3.2.0|linux_ppc   |39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "v3.2.0|linux_x86_64|c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "v3.2.0|macos_x86_64|1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
    ]
    default_url_template = "https://foobar.org/bin/v{version}/foobar-{version}-{platform}.tgz"
    default_url_platform_mapping = {
        "macos_x86_64": "osx-x86_64",
        "macos_arm64": "osx-x86_64",
        "linux_x86_64": "linux-x86_64",
    }

    def generate_exe(self, plat: Platform) -> str:
        return f"foobar-{self.version}/bin/foobar"


@pytest.mark.parametrize(
    "version, action, assert_expectation, expect_logged",
    [
        (
            "v1.2.3",
            UnsupportedVersionUsage.RaiseError,
            pytest.raises(
                UnsupportedVersion,
                match=re.escape(
                    softwrap(
                        """
                        The option [foobar].version is set to v1.2.3, which is not compatible with what this release of Pants expects: foobar<3.8,>3.2.1.
                        Please update the version to a supported value, or consider using a different Pants release if you cannot change the version.
                        Alternatively, update [foobar].use_unsupported_version to be 'warning'.
                        """
                    )
                ),
            ),
            None,
        ),
        (
            "v3.2.2",
            UnsupportedVersionUsage.RaiseError,
            pytest.raises(
                UnknownVersion, match="No known version of foobar v3.2.2 for macos_x86_64 found in"
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
                UnsupportedVersion,
                match=re.escape(
                    softwrap(
                        """
                        The option [foobar].version is set to v3.8.0, which is not compatible with what this release of Pants expects: foobar<3.8,>3.2.1.
                        Please update the version to a supported value, or consider using a different Pants release if you cannot change the version.
                        Alternatively, update [foobar].use_unsupported_version to be 'warning'.
                        """
                    )
                ),
            ),
            None,
        ),
        (
            "v3.8.0",
            UnsupportedVersionUsage.LogWarning,
            pytest.raises(
                UnknownVersion, match="No known version of foobar v3.8.0 for macos_x86_64 found in"
            ),
            [
                (
                    logging.WARNING,
                    softwrap(
                        """
                        The option [foobar].version is set to v3.8.0, which is not compatible with what this release of Pants expects: foobar<3.8,>3.2.1.
                        Please update the version to a supported value, or consider using a different Pants release if you cannot change the version.
                        Alternatively, you can ignore this warning (at your own peril) by adding this to the GLOBAL section of pants.toml:
                        ignore_warnings = ["The option [foobar].version is set to"].
                        """
                    ),
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
        ).get_request(Platform.macos_x86_64)

    if expect_logged:
        assert len(caplog.records) == len(expect_logged)
        for idx, (lvl, msg) in enumerate(expect_logged):
            log_record = caplog.records[idx]
            assert msg in log_record.message
            assert lvl == log_record.levelno
    else:
        assert not caplog.records
