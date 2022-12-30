# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from pants.engine.download_file import URLDownloadHandler
from pants.engine.fs import Digest, NativeDownloadFile
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap

CONTENT_TYPE = "binary/octet-stream"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AWSCredentials:
    creds: Any


@rule
async def access_aws_credentials() -> AWSCredentials:
    try:
        from botocore import credentials, session
    except ImportError:
        logger.warning(
            softwrap(
                """
                In order to resolve s3:// URLs, Pants must load AWS credentials. To do so, `botocore`
                must be importable in Pants' environment.

                To do that add an entry to `[GLOBAL].plugins` of a pip-resolvable package to download from PyPI.
                (E.g. `botocore == 1.29.39`). Note that the `botocore` package from PyPI at the time
                of writing is >70MB, so an alternate package providing the `botocore` modules may be
                advisable.
                """
            )
        )
        raise

    session = session.get_session()
    creds = credentials.create_credential_resolver(session).load_credentials()

    return AWSCredentials(creds)


# NB: The URL is expected to be in path-style
# See https://docs.aws.amazon.com/AmazonS3/latest/userguide/VirtualHosting.html
def _get_aws_auth_headers(url: str, aws_credentials: AWSCredentials):
    from botocore import auth  # pants: no-infer-dep

    request = SimpleNamespace(
        url=url,
        headers={},
        method="GET",
        auth_path=None,
    )
    auth.HmacV1Auth(aws_credentials.creds).add_auth(request)
    return request.headers


class DownloadS3SchemeURL(URLDownloadHandler):
    match_scheme = "s3"


@rule
async def download_file_from_s3_scheme(
    request: DownloadS3SchemeURL, aws_credentials: AWSCredentials
) -> Digest:
    parsed_url = urlparse(request.url)
    bucket = parsed_url.netloc
    key = parsed_url.path
    http_url = f"https://s3.amazonaws.com/{bucket}{key}"
    headers = _get_aws_auth_headers(http_url, aws_credentials)

    digest = await Get(
        Digest,
        NativeDownloadFile(
            url=http_url,
            expected_digest=request.expected_digest,
            auth_headers=headers,
        ),
    )
    return digest


class DownloadS3AuthorityVirtualHostedStyleURL(URLDownloadHandler):
    match_authority = "*.s3*amazonaws.com"


@rule
async def download_file_from_virtual_hosted_s3_authority(
    request: DownloadS3AuthorityVirtualHostedStyleURL, aws_credentials: AWSCredentials
) -> Digest:
    parsed_url = urlparse(request.url)
    bucket = parsed_url.netloc.split(".", 1)[0]
    # NB: Turn this into a path-style request
    path_style_url = f"https://s3.amazonaws.com/{bucket}{parsed_url.path}"
    if parsed_url.query:
        path_style_url += f"?{parsed_url.query}"
    headers = _get_aws_auth_headers(path_style_url, aws_credentials)

    digest = await Get(
        Digest,
        NativeDownloadFile(
            url=request.url,
            expected_digest=request.expected_digest,
            auth_headers=headers,
        ),
    )
    return digest


class DownloadS3AuthorityPathStyleURL(URLDownloadHandler):
    match_authority = "s3.*amazonaws.com"


@rule
async def download_file_from_path_s3_authority(
    request: DownloadS3AuthorityPathStyleURL, aws_credentials: AWSCredentials
) -> Digest:
    headers = _get_aws_auth_headers(request.url, aws_credentials)
    digest = await Get(
        Digest,
        NativeDownloadFile(
            url=request.url,
            expected_digest=request.expected_digest,
            auth_headers=headers,
        ),
    )
    return digest


def rules():
    return [
        UnionRule(URLDownloadHandler, DownloadS3SchemeURL),
        UnionRule(URLDownloadHandler, DownloadS3AuthorityVirtualHostedStyleURL),
        UnionRule(URLDownloadHandler, DownloadS3AuthorityPathStyleURL),
        *collect_rules(),
    ]
