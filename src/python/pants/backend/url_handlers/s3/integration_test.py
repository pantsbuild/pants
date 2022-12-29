# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from pants.backend.url_handlers.s3.register import DownloadS3URLHandler
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
            QueryRule(Snapshot, [DownloadS3URLHandler]),
        ],
        isolated_local_store=True,
    )


@pytest.fixture
def monkeypatch_botocore(monkeypatch):
    botocore = SimpleNamespace()
    fake_session = object()
    fake_creds = SimpleNamespace(access_key="ACCESS", secret_key="SECRET")
    botocore.session = SimpleNamespace(get_session=lambda: fake_session)

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
        return SimpleNamespace(
            add_auth=lambda request: request.headers.__setitem__("AUTH", "TOKEN")
        )

    botocore.auth = SimpleNamespace(SigV3Auth=fake_auth_ctor)

    monkeypatch.setitem(sys.modules, "botocore", botocore)


@pytest.fixture
def replace_url(monkeypatch):
    def with_port(port):
        old_native_download_file_init = NativeDownloadFile.__init__

        def new_init(self, **kwargs):
            assert kwargs["url"] == "https://bucket.s3.amazonaws.com/keypart1/keypart2/file.txt"
            kwargs["url"] = f"http://localhost:{port}/file.txt"
            return old_native_download_file_init(self, **kwargs)

        monkeypatch.setattr(NativeDownloadFile, "__init__", new_init)

    return with_port


def test_download_s3(rule_runner: RuleRunner, monkeypatch_botocore, replace_url) -> None:
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

    with http_server(S3HTTPHandler) as port:
        replace_url(port)
        snapshot = rule_runner.request(
            Snapshot,
            [DownloadS3URLHandler("s3://bucket/keypart1/keypart2/file.txt", DOWNLOADS_FILE_DIGEST)],
        )
    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST
