# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import ClassVar, Optional
from urllib.parse import urlparse

from pants.engine.fs import Digest, DownloadFile, NativeDownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, union


@union
@dataclass(frozen=True)
class URLDownloadHandler:
    """Union base for custom URL handler.

    To register a custom URL handler:
    - Subclass this class and declare one or both of the ClassVars.
    - Declare a rule that takes in your class type and returns a `Digest`.
    - Register your union member in your `rules()`: `UnionRule(URLDownloadHandler, YourClass)`.

    Example:

        class S3DownloadHandler(URLDownloadHandler):
            match_scheme = "s3"

        @rule
        async def download_s3_file(request: S3DownloadHandler) -> Digest:
            # Lookup auth tokens, etc...
            # Ideally, download the file using `NativeDownloadFile()`
            return digest

        def rules():
            return [
                *collect_rules(),
                UnionRule(URLDownloadHandler, S3DownloadHandler),
            ]
    """

    match_scheme: ClassVar[Optional[str]] = None
    """The scheme to match (e.g. 'ftp' or 's3') or `None` to match all schemes.

    Note that 'http' and 'https' are two different schemes. In order to match either, you'll need to
    register both.
    """

    match_authority: ClassVar[Optional[str]] = None
    """The authority to match (e.g. 'pantsbuild.org' or 's3.amazonaws.com') or `None` to match all schemes.

    Note that the authority matches userinfo (e.g. 'me@pantsbuild.org' or 'me:password@pantsbuild.org')
    as well as port (e.g. 'pantsbuild.org:80').
    """

    url: str
    expected_digest: FileDigest


@rule
async def download_file(
    request: DownloadFile,
    union_membership: UnionMembership,
) -> Digest:
    parsed_url = urlparse(request.url)
    handlers = union_membership.get(URLDownloadHandler)
    for handler in handlers:
        matches_scheme = handler.match_scheme is None or handler.match_scheme == parsed_url.scheme
        matches_authority = (
            handler.match_authority is None or handler.match_authority == parsed_url.netloc
        )
        if matches_scheme or matches_authority:
            digest = await Get(
                Digest, URLDownloadHandler, handler(request.url, request.expected_digest)
            )
            break
    else:
        digest = await Get(Digest, NativeDownloadFile(request.url, request.expected_digest))

    return digest


def rules():
    return collect_rules()
