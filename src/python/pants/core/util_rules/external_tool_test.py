# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import re
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from textwrap import dedent
from typing import Tuple
from zipfile import ZipFile

import pytest

from pants.core.goals import run
from pants.core.target_types import ExternalToolTarget, HTTPSource
from pants.core.util_rules.external_tool import (
    ExternalTool,
    ExternalToolError,
    ExternalToolRequest,
    TemplatedExternalTool,
    UnknownVersion,
    UnsupportedVersion,
    UnsupportedVersionUsage,
)
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import DownloadFile, FileDigest
from pants.engine.platform import Platform
from pants.testutil.option_util import create_subsystem
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import RuleRunner, mock_console
from pants.util.contextutil import http_server
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
    ]

    def generate_url(self, plat: Platform) -> str:
        if plat == Platform.macos_x86_64:
            plat_str = "osx-x86_64"
        elif plat == Platform.linux_x86_64:
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
        "3.2.0|macos_x86_64|1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "3.2.0|linux_ppc   |39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux_x86_64|c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.4.7|macos_x86_64|9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.4.7|linux_x86_64|a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
    ]
    default_url_template = "https://foobar.org/bin/v{version}/foobar-{version}-{platform}.tgz"
    default_url_platform_mapping = {
        "macos_x86_64": "osx-x86_64",
        "macos_arm64": "osx-x86_64",
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

    with pytest.raises(UnknownVersion):
        create_subsystem(
            FooBar, version="9.9.9", known_versions=FooBar.default_known_versions
        ).get_request(Platform.macos_x86_64)


class ConstrainedTool(TemplatedExternalTool):
    name = "foobar"
    options_scope = "foobar"
    version_constraints = ">3.2.1, <3.8"
    default_version = "v3.4.7"
    default_known_versions = [
        "v3.2.0|macos_x86_64|1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "v3.2.0|linux_ppc   |39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "v3.2.0|linux_x86_64|c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "v3.4.7|macos_x86_64|9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "v3.4.7|linux_x86_64|a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
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


def test_external_tool_target() -> None:
    script = dedent(
        """\
        #!/usr/bin/env python
        from __future__ import print_function
        import sys
        print(sys.argv)
        """
    ).encode("utf-8")

    _buffer = BytesIO()
    with ZipFile(_buffer, mode="w") as zipfile:
        zipfile.writestr("parrot_helper.py", data=script)
        zipfile.writestr("parrot.py", data=b"#!/usr/bin/env python\nimport parrot_helper")

    zipped_script = _buffer.getvalue()

    class StubHandler(BaseHTTPRequestHandler):
        def _get_content_info(self) -> Tuple[str, bytes]:
            return {
                "py": ("text/utf-8", script),
                "zip": ("application/zip", zipped_script),
            }[self.path.split(".")[-1]]

        def do_HEAD(self):
            content_type, content = self._get_content_info()
            self.send_headers(content_type, content)

        def do_GET(self):
            content_type, content = self._get_content_info()
            self.send_headers(content_type, content)
            self.wfile.write(content)

        def send_headers(self, content_type: str, content: bytes):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", f"{len(content)}")
            self.end_headers()

    rule_runner = RuleRunner(
        rules=[
            *external_tool_rules(),
            *run.rules(),
        ],
        target_types=[ExternalToolTarget],
        objects={"http_source": HTTPSource},
    )

    with http_server(StubHandler) as port:

        def get_source_fields(suffix: str) -> str:
            content = {"py": script, "zip": zipped_script}[suffix]
            return ",".join(
                [
                    f'url="http://localhost:{port}/parrot.{suffix}"',
                    f'sha256="{hashlib.sha256(content).hexdigest()}"',
                    f"len={len(content)}",
                ]
            )

        rule_runner.write_files(
            {
                "BUILD": dedent(
                    f"""\
                    external_tool(
                        name="script",
                        source=http_source({get_source_fields("py")})
                    )
                    external_tool(
                        name="script-with-exe-set",
                        source=http_source({get_source_fields("py")}),
                        exe="parrot.py",
                    )
                    external_tool(
                        name="script-with-exe-set-dot-slash",
                        source=http_source({get_source_fields("py")}),
                        exe="./parrot.py",
                    )
                    external_tool(
                        name="script-renamed",
                        source=http_source(
                            {get_source_fields("py")},
                            filename="psittacines.py",
                        ),
                    )
                    external_tool(
                        name="script-renamed-with-exe-set",
                        source=http_source(
                            {get_source_fields("py")},
                            filename="psittacines.py",
                        ),
                        exe="psittacines.py",
                    )
                    external_tool(
                        name="zipped",
                        source=http_source({get_source_fields("zip")}),
                        exe="parrot.py",
                    )
                    external_tool(
                        name="zipped-renamed",
                        source=http_source(
                            {get_source_fields("zip")},
                            filename="quiet_parrot.zip",
                        ),
                        exe="parrot.py",
                    )
                    external_tool(
                        name="zipped-missing-exe",
                        source=http_source({get_source_fields("zip")}),
                    )
                    """
                ),
            }
        )
        for tgt_name, pathname in [
            ("script", "parrot.py"),
            ("script-with-exe-set", "parrot.py"),
            ("script-with-exe-set-dot-slash", "parrot.py"),
            ("script-renamed", "psittacines.py"),
            ("script-renamed-with-exe-set", "psittacines.py"),
            ("zipped", "parrot.py"),
            ("zipped-renamed", "parrot.py"),
        ]:
            with mock_console(rule_runner.options_bootstrapper) as (console, stdout_reader):
                rule_runner.run_goal_rule(
                    run.Run,
                    args=[f":{tgt_name}", "--", "Hello World"],
                    env_inherit={"PATH", "PYENV_ROOT", "HOME"},
                )
                stdout = stdout_reader.get_stdout()
                assert f"{tgt_name}/{pathname}" in stdout
                assert "Hello World" in stdout
        with mock_console(rule_runner.options_bootstrapper) as (console, stdout_reader):
            with pytest.raises(
                Exception,
                match="The `exe` field of the `extracted_target`",
            ):
                rule_runner.run_goal_rule(
                    run.Run,
                    args=[":zipped-missing-exe", "--", "Hello World"],
                    env_inherit={"PATH", "PYENV_ROOT", "HOME"},
                )
