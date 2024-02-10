# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import ClassVar, Optional
from urllib.parse import urlparse

from pants.engine.fs import Digest, DownloadFile, NativeDownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.util.strutil import bullet_list, softwrap


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

    The scheme is matched using `fnmatch`, see https://docs.python.org/3/library/fnmatch.html for more
    information.
    """

    match_authority: ClassVar[Optional[str]] = None
    """The authority to match (e.g. 'pantsbuild.org' or 's3.amazonaws.com') or `None` to match all
    authorities.

    The authority is matched using `fnmatch`, see https://docs.python.org/3/library/fnmatch.html for more
    information.

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
    matched_handlers = []
    for handler in handlers:
        matches_scheme = handler.match_scheme is None or fnmatch(
            parsed_url.scheme, handler.match_scheme
        )
        matches_authority = handler.match_authority is None or fnmatch(
            parsed_url.netloc, handler.match_authority
        )
        if matches_scheme and matches_authority:
            matched_handlers.append(handler)

    if len(matched_handlers) > 1:
        raise Exception(
            softwrap(
                f"""
                Too many registered URL handlers match the URL '{request.url}'.

                Matched handlers:
                {bullet_list(map(str, handlers))}
                """
            )
        )
    if len(matched_handlers) == 1:
        handler = matched_handlers[0]
        return await Get(Digest, URLDownloadHandler, handler(request.url, request.expected_digest))

    return await Get(Digest, NativeDownloadFile(request.url, request.expected_digest))


def rules():
    return collect_rules()
