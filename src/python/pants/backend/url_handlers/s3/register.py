# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from pants.backend.url_handlers.s3.subsystem import S3AuthSigning, S3Subsystem
from pants.engine.download_file import URLDownloadHandler
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import Digest, NativeDownloadFile
from pants.engine.internals.native_engine import EMPTY_FILE_DIGEST, FileDigest
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.intrinsics import download_file
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.strutil import softwrap

CONTENT_TYPE = "binary/octet-stream"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AWSCredentials:
    creds: Any
    default_region: str | None


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

    env_vars = await environment_vars_subset(
        EnvironmentVarsRequest(
            [
                "AWS_PROFILE",
                "AWS_REGION",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
            ]
        ),
        **implicitly(
            {
                local_environment_name.val: EnvironmentName,
            }
        ),
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
    default_region = session.get_config_variable("region")

    return AWSCredentials(creds=creds, default_region=default_region)


@dataclass(frozen=True)
class S3DownloadFile:
    region: str
    bucket: str
    key: str
    query: str
    expected_digest: FileDigest


@rule
async def download_from_s3(
    request: S3DownloadFile,
    aws_credentials: AWSCredentials,
    global_options: GlobalOptions,
    s3_subsystem: S3Subsystem,
) -> Digest:
    from botocore import auth, compat, exceptions  # pants: no-infer-dep

    virtual_hosted_url = f"https://{request.bucket}.s3.amazonaws.com/{request.key}"
    if request.region:
        virtual_hosted_url = (
            f"https://{request.bucket}.s3.{request.region}.amazonaws.com/{request.key}"
        )
    if request.query:
        virtual_hosted_url += f"?{request.query}"

    headers = compat.HTTPHeaders()
    signer = None
    http_request = None

    if s3_subsystem.auth_signing == S3AuthSigning.SIGV4:
        # sigv4 uses the virtual_hosted_url for the auth request
        http_request = SimpleNamespace(
            url=virtual_hosted_url,
            headers=headers,
            method="GET",
            auth_path=None,
            data=None,
            params={},
            context={},
            body={},
        )

        # Add x-amz-content-SHA256 as per boto code
        # ref link - https://github.com/boto/botocore/blob/547b20801770c8ea4255ee9c3b809fea6b9f6bc4/botocore/auth.py#L52C1-L54C2
        headers.add_header(
            "X-Amz-Content-SHA256",
            EMPTY_FILE_DIGEST.fingerprint,
        )

        # A region is required to sign the request with sigv4. If we don't know where the bucket is,
        # default to the region from the credentials
        signing_region = request.region or aws_credentials.default_region
        if not signing_region:
            raise Exception(
                "An aws region is required to sign requests with sigv4. Please specify a region in the url or configure the default region in aws config or environment variables."
            )

        signer = auth.SigV4Auth(aws_credentials.creds, "s3", signing_region)

    else:
        assert s3_subsystem.auth_signing == S3AuthSigning.HMACV1
        # NB: The URL for HmacV1 auth is expected to be in path-style
        path_style_url = "https://s3"
        if request.region:
            path_style_url += f".{request.region}"
        path_style_url += f".amazonaws.com/{request.bucket}/{request.key}"
        if request.query:
            path_style_url += f"?{request.query}"

        http_request = SimpleNamespace(
            url=path_style_url,
            headers=headers,
            method="GET",
            auth_path=None,
        )
        signer = auth.HmacV1Auth(aws_credentials.creds)

    # NB: The added Auth header doesn't need to be valid when accessing a public bucket. When
    # hand-testing, you MUST test against a private bucket to ensure it works for private buckets too.
    try:
        signer.add_auth(http_request)
    except exceptions.NoCredentialsError:
        pass  # The user can still access public S3 buckets without credentials

    return await download_file(
        NativeDownloadFile(
            url=virtual_hosted_url,
            expected_digest=request.expected_digest,
            auth_headers=http_request.headers,
            retry_delay_duration=global_options.file_downloads_retry_delay,
            max_attempts=global_options.file_downloads_max_attempts,
        )
    )


class DownloadS3SchemeURL(URLDownloadHandler):
    match_scheme = "s3"


@rule
async def download_file_from_s3_scheme(request: DownloadS3SchemeURL) -> Digest:
    split = urlsplit(request.url)
    return await download_from_s3(
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
    return await download_from_s3(
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
    return await download_from_s3(
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
