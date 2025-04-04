# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from pants.engine.download_file import URLDownloadHandler
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import Digest, NativeDownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.strutil import softwrap

CONTENT_TYPE = "binary/octet-stream"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AWSCredentials:
    creds: Any


@rule
async def access_aws_credentials(
    local_environment_name: ChosenLocalEnvironmentName,
) -> AWSCredentials:
    try:
        from botocore import credentials
        from botocore import session as boto_session
    except ImportError:
        logger.warning(
            softwrap(
                """
                In order to resolve s3:// URLs, Pants must load AWS credentials. To do so, `botocore`
                must be importable in Pants' environment.

                To do that add an entry to `[GLOBAL].plugins` of a pip-resolvable package to download from PyPI.
                (E.g. `botocore == 1.29.39`). Note that the `botocore` package from PyPI at the time
                of writing is >70MB, so an alternate package providing the `botocore` modules may be
                advisable (such as [`botocore-a-la-carte`](https://pypi.org/project/botocore-a-la-carte/)).
                """
            )
        )
        raise

    env_vars = await Get(
        EnvironmentVars,
        {
            EnvironmentVarsRequest(
                [
                    "AWS_PROFILE",
                    "AWS_REGION",
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "AWS_SESSION_TOKEN",
                ]
            ): EnvironmentVarsRequest,
            local_environment_name.val: EnvironmentName,
        },
    )

    session = boto_session.Session()

    aws_profile = env_vars.get("AWS_PROFILE")
    if aws_profile:
        session.set_config_variable("profile", aws_profile)

    aws_region = env_vars.get("AWS_REGION")
    if aws_region:
        session.set_config_variable("region", aws_region)

    aws_access_key = env_vars.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = env_vars.get("AWS_SECRET_ACCESS_KEY")
    aws_session_token = env_vars.get("AWS_SESSION_TOKEN")
    if aws_access_key and aws_secret_key:
        session.set_credentials(
            credentials.Credentials(
                access_key=aws_access_key,
                secret_key=aws_secret_key,
                token=aws_session_token,
            )
        )

    creds = credentials.create_credential_resolver(session).load_credentials()

    return AWSCredentials(creds)


@dataclass(frozen=True)
class S3DownloadFile:
    region: str
    bucket: str
    key: str
    query: str
    expected_digest: FileDigest


@rule
async def download_from_s3(
    request: S3DownloadFile, aws_credentials: AWSCredentials, global_options: GlobalOptions
) -> Digest:
    from botocore import auth, compat, exceptions  # pants: no-infer-dep

    # NB: The URL for auth is expected to be in path-style
    path_style_url = "https://s3"
    if request.region:
        path_style_url += f".{request.region}"
    path_style_url += f".amazonaws.com/{request.bucket}/{request.key}"
    if request.query:
        path_style_url += f"?{request.query}"

    headers = compat.HTTPHeaders()
    http_request = SimpleNamespace(
        url=path_style_url,
        headers=headers,
        method="GET",
        auth_path=None,
    )
    # NB: The added Auth header doesn't need to be valid when accessing a public bucket. When
    # hand-testing, you MUST test against a private bucket to ensure it works for private buckets too.
    signer = auth.HmacV1Auth(aws_credentials.creds)
    try:
        signer.add_auth(http_request)
    except exceptions.NoCredentialsError:
        pass  # The user can still access public S3 buckets without credentials

    virtual_hosted_url = f"https://{request.bucket}.s3"
    if request.region:
        virtual_hosted_url += f".{request.region}"
    virtual_hosted_url += f".amazonaws.com/{request.key}"
    if request.query:
        virtual_hosted_url += f"?{request.query}"

    return await Get(
        Digest,
        NativeDownloadFile(
            url=virtual_hosted_url,
            expected_digest=request.expected_digest,
            auth_headers=http_request.headers,
            retry_delay_duration=global_options.file_downloads_retry_delay,
            max_attempts=global_options.file_downloads_max_attempts,
        ),
    )


class DownloadS3SchemeURL(URLDownloadHandler):
    match_scheme = "s3"


@rule
async def download_file_from_s3_scheme(request: DownloadS3SchemeURL) -> Digest:
    split = urlsplit(request.url)
    return await Get(
        Digest,
        S3DownloadFile(
            region="",
            bucket=split.netloc,
            key=split.path[1:],
            query=split.query,
            expected_digest=request.expected_digest,
        ),
    )


class DownloadS3AuthorityVirtualHostedStyleURL(URLDownloadHandler):
    match_authority = "*.s3*amazonaws.com"


@rule
async def download_file_from_virtual_hosted_s3_authority(
    request: DownloadS3AuthorityVirtualHostedStyleURL,
) -> Digest:
    split = urlsplit(request.url)
    bucket, aws_netloc = split.netloc.split(".", 1)
    return await Get(
        Digest,
        S3DownloadFile(
            region=aws_netloc.split(".")[1] if aws_netloc.count(".") == 3 else "",
            bucket=bucket,
            key=split.path[1:],
            query=split.query,
            expected_digest=request.expected_digest,
        ),
    )


class DownloadS3AuthorityPathStyleURL(URLDownloadHandler):
    match_authority = "s3.*amazonaws.com"


@rule
async def download_file_from_path_s3_authority(request: DownloadS3AuthorityPathStyleURL) -> Digest:
    split = urlsplit(request.url)
    _, bucket, key = split.path.split("/", 2)
    return await Get(
        Digest,
        S3DownloadFile(
            region=split.netloc.split(".")[1] if split.netloc.count(".") == 3 else "",
            bucket=bucket,
            key=key,
            query=split.query,
            expected_digest=request.expected_digest,
        ),
    )


def rules():
    return [
        UnionRule(URLDownloadHandler, DownloadS3SchemeURL),
        UnionRule(URLDownloadHandler, DownloadS3AuthorityVirtualHostedStyleURL),
        UnionRule(URLDownloadHandler, DownloadS3AuthorityPathStyleURL),
        *collect_rules(),
    ]
