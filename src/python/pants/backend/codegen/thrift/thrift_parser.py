# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from pants.backend.codegen.thrift.target_types import ThriftSourceField
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

_QUOTE_CHAR = r"(?:'|\")"
# NB: We don't specify what a valid file name looks like to avoid accidentally breaking unicode.
_FILE_NAME = r"(.+?\.thrift)"
_IMPORT_REGEX = re.compile(rf"include\s+{_QUOTE_CHAR}{_FILE_NAME}{_QUOTE_CHAR}\s*")

# NB: We don't specify what a valid namespace looks like to avoid accidentally breaking unicode,
# but we do limit the namespace language because that is provided by Thrift.
_NAMESPACE_REGEX = re.compile(r"namespace\s+([a-z]+)\s+(.+)\s*")


@dataclass(frozen=True)
class ParsedThrift:
    imports: FrozenOrderedSet[str]
    # Note that Thrift only allows one namespace per language per file; later namespaces overwrite
    # earlier ones.
    namespaces: FrozenDict[str, str]


@dataclass(frozen=True)
class ParsedThriftRequest(EngineAwareParameter):
    sources_field: ThriftSourceField
    extra_namespace_directives: tuple[str, ...] = ()

    def debug_hint(self) -> str:
        return self.sources_field.file_path


@rule
async def parse_thrift_file(request: ParsedThriftRequest) -> ParsedThrift:
    sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    digest_contents = await Get(DigestContents, Digest, sources.snapshot.digest)
    assert len(digest_contents) == 1

    file_content = digest_contents[0].content.decode()
    extra_namespaces: Mapping[str, str] = {}
    if request.extra_namespace_directives:
        for directive in request.extra_namespace_directives:
            extra_namespace_pattern = re.compile(rf"{directive}\s+([a-z]+)\s+(.+)\s*")
            extra_namespaces = {
                **extra_namespaces,
                **dict(extra_namespace_pattern.findall(file_content)),
            }

    return ParsedThrift(
        imports=FrozenOrderedSet(_IMPORT_REGEX.findall(file_content)),
        namespaces=FrozenDict({**dict(_NAMESPACE_REGEX.findall(file_content)), **extra_namespaces}),
    )


def rules():
    return collect_rules()
