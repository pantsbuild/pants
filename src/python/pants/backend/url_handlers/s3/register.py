# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from pants.engine.download_file import URLDownloadHandler
from pants.engine.fs import Digest, NativeDownloadFile
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap

CONTENT_TYPE = "binary/octet-stream"


logger = logging.getLogger(__name__)


class DownloadS3URLHandler(URLDownloadHandler):
    matches_scheme = "s3"


@dataclass(frozen=True)
class AWSCredentials:
    access_key_id: str
    secret_access_key: bytes


@rule
async def access_aws_credentials() -> AWSCredentials:
    try:
        import botocore.credentials  # pants: no-infer-dep
        import botocore.session  # pants: no-infer-dep
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

    session = botocore.session.get_session()
    creds = botocore.credentials.create_credential_resolver(session).load_credentials()

    return AWSCredentials(
        access_key_id=creds.access_key,
        secret_access_key=creds.secret_key.encode("utf-8"),
    )


@rule
async def download_s3_file(
    request: DownloadS3URLHandler, aws_credentials: AWSCredentials
) -> Digest:
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    parsed_url = urlparse(request.url)
    bucket = parsed_url.netloc
    key = parsed_url.path
    signature = hmac.digest(
        aws_credentials.secret_access_key,
        f"GET\n\n{CONTENT_TYPE}\n{now}\n{key}".encode("ascii"),
        digest="sha1",
    )

    digest = await Get(
        Digest,
        NativeDownloadFile(
            url=f"https://{bucket}.s3.amazonaws.com{key}",
            expected_digest=request.expected_digest,
            auth_headers={
                "CONTENT_TYPE": CONTENT_TYPE,
                "DATE": now,
                "AUTHENTICATION": f"AWS {aws_credentials.access_key_id}:{signature}",
            },
        ),
    )
    return digest


def rules():
    return [
        UnionRule(URLDownloadHandler, DownloadS3URLHandler),
        *collect_rules(),
    ]
