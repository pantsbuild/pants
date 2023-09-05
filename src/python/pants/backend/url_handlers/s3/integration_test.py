# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from pants.backend.url_handlers.s3.register import (
    DownloadS3AuthorityPathStyleURL,
    DownloadS3AuthorityVirtualHostedStyleURL,
    DownloadS3SchemeURL,
)
from pants.backend.url_handlers.s3.register import rules as s3_rules
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
        ],
        isolated_local_store=True,
    )


@pytest.fixture
def monkeypatch_botocore(monkeypatch):
    def do_patching(expected_url):
        botocore = SimpleNamespace()
        botocore.exceptions = SimpleNamespace(NoCredentialsError=Exception)
        fake_session = object()
        fake_creds = SimpleNamespace(access_key="ACCESS", secret_key="SECRET", token=None)
        botocore.session = SimpleNamespace(get_session=lambda: fake_session)
        # NB: HTTPHeaders is just a simple subclass of HTTPMessage
        botocore.compat = SimpleNamespace(HTTPHeaders=HTTPMessage)

        def fake_resolver_creator(session):
            assert session is fake_session
            return SimpleNamespace(load_credentials=lambda: fake_creds)

        def fake_creds_ctor(access_key, secret_key):
            assert access_key == fake_creds.access_key
            assert secret_key == fake_creds.secret_key
            return fake_creds

        botocore.credentials = SimpleNamespace(
            create_credential_resolver=fake_resolver_creator, Credentials=fake_creds_ctor
        )

        def fake_auth_ctor(creds):
            assert creds is fake_creds

            def add_auth(request):
                request.url == expected_url
                request.headers["AUTH"] = "TOKEN"

            return SimpleNamespace(add_auth=add_auth)

        botocore.auth = SimpleNamespace(HmacV1Auth=fake_auth_ctor)

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
    "request_url, expected_auth_url, expected_native_url, req_type",
    [
        (
            "s3://bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3SchemeURL,
        ),
        # Path-style
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
        ),
        (
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityPathStyleURL,
        ),
        (
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityPathStyleURL,
        ),
        # Virtual-hosted-style
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
        ),
        (
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://s3.amazonaws.com/bucket/keypart1/keypart2/file.txt?versionId=ABC123",
            "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt?versionId=ABC123",
            DownloadS3AuthorityVirtualHostedStyleURL,
        ),
        (
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            "https://s3.us-west-2.amazonaws.com/bucket/keypart1/keypart2/file.txt",
            "https://bucket.s3.us-west-2.amazonaws.com/keypart1/keypart2/file.txt",
            DownloadS3AuthorityVirtualHostedStyleURL,
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

    monkeypatch_botocore(expected_auth_url)
    with http_server(S3HTTPHandler) as port:
        replace_url(expected_native_url, port)
        snapshot = rule_runner.request(
            Snapshot,
            [req_type(request_url, DOWNLOADS_FILE_DIGEST)],
        )
    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST
