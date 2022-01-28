# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, TypeVar

from pants.engine.process import BinaryPath, BinaryPathRequest, BinaryPaths, BinaryPathTest
from pants.engine.rules import Get, collect_rules, rule

T = TypeVar("T", bound="PosixBinary")


class PosixBinary(BinaryPath):

    binary_name: ClassVar[str]
    binary_test: ClassVar[BinaryPathTest | None]

    @classmethod
    def using(cls: type[T], binary_path: BinaryPath) -> T:
        return cls(path=binary_path.path, fingerprint=binary_path.fingerprint)


@dataclass(frozen=True)
class PosixBinaryRequest:
    type: type[PosixBinary]


class LnBinary(PosixBinary):
    binary_name = "ln"
    binary_test = None


SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


@rule
async def find_ln() -> LnBinary:
    ln = await Get(BinaryPath, PosixBinaryRequest(LnBinary))
    return LnBinary.using(ln)


@rule
async def find_posix_binary(request: PosixBinaryRequest) -> BinaryPath:
    path_request = BinaryPathRequest(
        binary_name=request.type.binary_name,
        search_path=SEARCH_PATHS,
        test=request.type.binary_test,
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, path_request)
    first_path = paths.first_path_or_raise(
        path_request, rationale=f"use `{path_request.binary_name}` in internal shell scripts"
    )
    return BinaryPath(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
