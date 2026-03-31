# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from pants.backend.url_handlers.s3.register import (
    AWSCredentials,
    DownloadS3AuthorityPathStyleURL,
    DownloadS3AuthorityVirtualHostedStyleURL,
    DownloadS3SchemeURL,
)
from pants.backend.url_handlers.s3.register import rules as s3_rules
from pants.backend.url_handlers.s3.subsystem import S3AuthSigning
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import Digest, FileDigest, NativeDownloadFile, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import http_server

DOWNLOADS_FILE_DIGEST = FileDigest(
    "8fcbc50cda241aee7238c71e87c27804e7abc60675974eaf6567aa16366bc105", 14
)
DOWNLOADS_EXPECTED_DIRECTORY_DIGEST = Digest(
    "4c9cf91fcd7ba1abbf7f9a0a1c8175556a82bee6a398e34db3284525ac24a3ad", 84
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *s3_rules(),
            QueryRule(Snapshot, [DownloadS3SchemeURL]),
            QueryRule(Snapshot, [DownloadS3AuthorityVirtualHostedStyleURL]),
            QueryRule(Snapshot, [DownloadS3AuthorityPathStyleURL]),
            QueryRule(AWSCredentials, []),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
        ],
        isolated_local_store=True,
    )


class NoCredentialsError(Exception):
    pass


@pytest.fixture
def monkeypatch_botocore(monkeypatch):
    def do_patching(expected_auth_url):
        botocore = SimpleNamespace()
        botocore.exceptions = SimpleNamespace(NoCredentialsError=NoCredentialsError)

        class FakeSession:
            def __init__(self):
                self.config_vars = {}
                self.creds = None

            def set_config_variable(self, key, value):
                self.config_vars.update({key: value})

            def get_config_variable(self, key):
                return self.config_vars.get(key) or "us-east-1"

            def get_credentials(self):
                if self.creds:
                    return self.creds

                key = "ACCESS"
                secret = "SECRET"
                # suffix the access key with the profile name to make testing easier
                if self.config_vars.get("profile"):
                    key = f"ACCESS_{self.config_vars.get('profile')}"
                return FakeCredentials.create(access_key=key, secret_key=secret)

            def set_credentials(self, creds):
                self.creds = creds

        class FakeCredentials:
            @staticmethod
            def create(access_key, secret_key, token=None):
                return SimpleNamespace(access_key=access_key, secret_key=secret_key, token=token)

        class FakeCredentialsResolver:
            def __init__(self, session):
                self.session = session

            def load_credentials(self):
                return self.session.get_credentials()

        botocore.session = SimpleNamespace(Session=lambda: FakeSession())
        botocore.compat = SimpleNamespace(HTTPHeaders=HTTPMessage)
        botocore.credentials = SimpleNamespace(
            create_credential_resolver=lambda session: FakeCredentialsResolver(session),
            Credentials=FakeCredentials.create,
        )

        def fake_auth_ctor(creds, service_name, region_name):
            assert service_name == "s3"
            assert region_name in ["us-east-1", "us-west-2"]

            def add_auth(request):
                assert request.url == expected_auth_url
                request.headers["AUTH"] = "TOKEN"

            return SimpleNamespace(add_auth=add_auth)

        def fake_hmac_v1_auth_ctor(creds):
            def add_auth(request):
                assert request.url == expected_auth_url
                request.headers["AUTH"] = "TOKEN"

            return SimpleNamespace(add_auth=add_auth)

        botocore.auth = SimpleNamespace(SigV4Auth=fake_auth_ctor, HmacV1Auth=fake_hmac_v1_auth_ctor)

        monkeypatch.setitem(sys.modules, "botocore", botocore)

    return do_patching


@pytest.fixture
def replace_url(monkeypatch):
    def with_port(expected_url, port):
        old_native_download_file_init = NativeDownloadFile.__init__

        def new_init(self, **kwargs):
            assert kwargs["url"] == expected_url
            kwargs["url"] = f"http://localhost:{port}/file.txt"
            return old_native_download_file_init(self, **kwargs)

        monkeypatch.setattr(NativeDownloadFile, "__init__", new_init)

    return with_port


@pytest.mark.parametrize(
    "request_url, expected_auth_url, expected_native_url, req_type, auth_type",
    [
        (
            "s3://bucket/keypart1/keypart2/file.txt",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3SchemeURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "s3://bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3SchemeURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "s3://bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3SchemeURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "s3://bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3SchemeURL,
            S3AuthSigning.SIGV4,
        ),
        # Path-style
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
            S3AuthSigning.SIGV4,
        ),
        # Virtual-hosted-style
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.SIGV4,
        ),
        (
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.HMACV1,
        ),
        (
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
            S3AuthSigning.SIGV4,
        ),
    ],
)
def test_download_s3(
    rule_runner: RuleRunner,
    monkeypatch_botocore,
    request_url: str,
    expected_auth_url: str,
    expected_native_url: str,
    req_type: type,
    auth_type: S3AuthSigning,
    replace_url,
) -> None:
    class S3HTTPHandler(BaseHTTPRequestHandler):
        response_text = b"Hello, client!"

        def do_HEAD(self):
            self.send_headers()

        def do_GET(self):
            self.send_headers()
            self.wfile.write(self.response_text)

        def send_headers(self):
            assert self.headers["AUTH"] == "TOKEN"
            self.send_response(200)
            self.send_header("Content-Type", "binary/octet-stream")
            self.send_header("Content-Length", f"{len(self.response_text)}")
            self.end_headers()

    rule_runner.set_options(
        args=[
            f"--s3-url-handler-auth-signing={auth_type.value}",
        ],
    )

    monkeypatch_botocore(expected_auth_url)
    with http_server(S3HTTPHandler) as port:
        replace_url(expected_native_url, port)
        snapshot = rule_runner.request(
            Snapshot,
            [req_type(request_url, DOWNLOADS_FILE_DIGEST)],
        )
    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_aws_credentials_caching(rule_runner: RuleRunner, monkeypatch_botocore) -> None:
    """Test that AWS credentials are properly cached based on environment variables."""
    monkeypatch_botocore("https://example.com")

    def set_aws_env_vars(rule_runner: RuleRunner, env_vars: dict[str, str]) -> None:
        rule_runner.set_options(
            args=[],
            env=env_vars,
        )

    set_aws_env_vars(rule_runner, {"AWS_PROFILE": "profile1"})

    creds1 = rule_runner.request(AWSCredentials, [])
    creds2 = rule_runner.request(AWSCredentials, [])
    assert creds1 is creds2
    assert creds1.creds.access_key == "ACCESS_profile1"

    # Request with different environment should return different credentials
    set_aws_env_vars(rule_runner, {"AWS_PROFILE": "profile2"})
    creds3 = rule_runner.request(AWSCredentials, [])
    assert creds1 is not creds3
    assert creds3.creds.access_key == "ACCESS_profile2"

    # Request with original environment should return original credentials
    set_aws_env_vars(rule_runner, {"AWS_PROFILE": "profile1"})
    creds4 = rule_runner.request(AWSCredentials, [])
    # N.B. Not totally sure why, but 'is' doesn't work here because of how set_options operates
    assert creds1 == creds4
