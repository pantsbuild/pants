# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    SystemBinariesSubsystem,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


class DirnameBinary(BinaryPath):
    pass


class IdBinary(BinaryPath):
    pass


class AwkBinary(BinaryPath):
    pass


class BasenameBinary(BinaryPath):
    pass


class CutBinary(BinaryPath):
    pass


class DfBinary(BinaryPath):
    pass


class ExprBinary(BinaryPath):
    pass


class GzipBinary(BinaryPath):
    pass


class HeadBinary(BinaryPath):
    pass


class SedBinary(BinaryPath):
    pass


class TailBinary(BinaryPath):
    pass


class WcBinary(BinaryPath):
    pass


class FindBinary(BinaryPath):
    pass


class Md5sumBinary(BinaryPath):
    pass


class DdBinary(BinaryPath):
    pass


class TestBinary(BinaryPath):
    pass


class PwdBinary(BinaryPath):
    pass


class XzBinary(BinaryPath):
    pass


class GpgBinary(BinaryPath):
    pass


class Base64Binary(BinaryPath):
    pass


class Bzip2Binary(BinaryPath):
    pass


class Bzip3Binary(BinaryPath):
    pass


class Lz4Binary(BinaryPath):
    pass


class LzopBinary(BinaryPath):
    pass


class ZstdBinary(BinaryPath):
    pass


class ShasumBinary(BinaryPath):
    pass


class DateBinary(BinaryPath):
    pass


class RmBinary(BinaryPath):
    pass


class DuBinary(BinaryPath):
    pass


class SortBinary(BinaryPath):
    pass


class XargsBinary(BinaryPath):
    pass


class ShBinary(BinaryPath):
    pass


class TrBinary(BinaryPath):
    pass


class CksumBinary(BinaryPath):
    pass


@rule(desc="Finding the `dirname` binary", level=LogLevel.DEBUG)
async def find_dirname(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DirnameBinary:
    request = BinaryPathRequest(
        binary_name="dirname", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dirname file")
    return DirnameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `id` binary", level=LogLevel.DEBUG)
async def find_id(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> IdBinary:
    request = BinaryPathRequest(binary_name="id", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="id file")
    return IdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `awk` binary", level=LogLevel.DEBUG)
async def find_awk(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> AwkBinary:
    request = BinaryPathRequest(binary_name="awk", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="awk file")
    return AwkBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `basename` binary", level=LogLevel.DEBUG)
async def find_basename(
    system_binaries: SystemBinariesSubsystem.EnvironmentAware,
) -> BasenameBinary:
    request = BinaryPathRequest(
        binary_name="basename", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="basename file")
    return BasenameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cut` binary", level=LogLevel.DEBUG)
async def find_cut(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CutBinary:
    request = BinaryPathRequest(binary_name="cut", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cut file")
    return CutBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `df` binary", level=LogLevel.DEBUG)
async def find_df(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DfBinary:
    request = BinaryPathRequest(binary_name="df", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="df file")
    return DfBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `expr` binary", level=LogLevel.DEBUG)
async def find_expr(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ExprBinary:
    request = BinaryPathRequest(binary_name="expr", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="expr file")
    return ExprBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gzip` binary", level=LogLevel.DEBUG)
async def find_gzip(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> GzipBinary:
    request = BinaryPathRequest(binary_name="gzip", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gzip file")
    return GzipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `head` binary", level=LogLevel.DEBUG)
async def find_head(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> HeadBinary:
    request = BinaryPathRequest(binary_name="head", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="head file")
    return HeadBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sed` binary", level=LogLevel.DEBUG)
async def find_sed(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> SedBinary:
    request = BinaryPathRequest(binary_name="sed", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sed file")
    return SedBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tail` binary", level=LogLevel.DEBUG)
async def find_tail(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TailBinary:
    request = BinaryPathRequest(binary_name="tail", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tail file")
    return TailBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `wc` binary", level=LogLevel.DEBUG)
async def find_wc(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> WcBinary:
    request = BinaryPathRequest(binary_name="wc", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="wc file")
    return WcBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `find` binary", level=LogLevel.DEBUG)
async def find_find(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> FindBinary:
    request = BinaryPathRequest(binary_name="find", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="find file")
    return FindBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `md5sum` binary", level=LogLevel.DEBUG)
async def find_md5sum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Md5sumBinary:
    request = BinaryPathRequest(
        binary_name="md5sum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="md5sum file")
    return Md5sumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `dd` binary", level=LogLevel.DEBUG)
async def find_dd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DdBinary:
    request = BinaryPathRequest(binary_name="dd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dd file")
    return DdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `test` binary", level=LogLevel.DEBUG)
async def find_test(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TestBinary:
    request = BinaryPathRequest(binary_name="test", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="test file")
    return TestBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `pwd` binary", level=LogLevel.DEBUG)
async def find_pwd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> PwdBinary:
    request = BinaryPathRequest(binary_name="pwd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="pwd file")
    return PwdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xz` binary", level=LogLevel.DEBUG)
async def find_xz(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> XzBinary:
    request = BinaryPathRequest(binary_name="xz", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xz file")
    return XzBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gpg` binary", level=LogLevel.DEBUG)
async def find_gpg(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> GpgBinary:
    request = BinaryPathRequest(binary_name="gpg", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gpg file")
    return GpgBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `base64` binary", level=LogLevel.DEBUG)
async def find_base64(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Base64Binary:
    request = BinaryPathRequest(
        binary_name="base64", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="base64 file")
    return Base64Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip2` binary", level=LogLevel.DEBUG)
async def find_bzip2(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Bzip2Binary:
    request = BinaryPathRequest(
        binary_name="bzip2", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip2 file")
    return Bzip2Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip3` binary", level=LogLevel.DEBUG)
async def find_bzip3(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Bzip3Binary:
    request = BinaryPathRequest(
        binary_name="bzip3", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip3 file")
    return Bzip3Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lz4` binary", level=LogLevel.DEBUG)
async def find_lz4(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Lz4Binary:
    request = BinaryPathRequest(binary_name="lz4", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lz4 file")
    return Lz4Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lzop` binary", level=LogLevel.DEBUG)
async def find_lzop(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> LzopBinary:
    request = BinaryPathRequest(binary_name="lzop", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lzop file")
    return LzopBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `zstd` binary", level=LogLevel.DEBUG)
async def find_zstd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ZstdBinary:
    request = BinaryPathRequest(binary_name="zstd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="zstd file")
    return ZstdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `shasum` binary", level=LogLevel.DEBUG)
async def find_shasum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ShasumBinary:
    request = BinaryPathRequest(
        binary_name="shasum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="shasum file")
    return ShasumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `date` binary", level=LogLevel.DEBUG)
async def find_date(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DateBinary:
    request = BinaryPathRequest(binary_name="date", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="date file")
    return DateBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `rm` binary", level=LogLevel.DEBUG)
async def find_rm(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> RmBinary:
    request = BinaryPathRequest(binary_name="rm", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="rm file")
    return RmBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `du` binary", level=LogLevel.DEBUG)
async def find_du(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DuBinary:
    request = BinaryPathRequest(binary_name="du", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="du file")
    return DuBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xargs` binary", level=LogLevel.DEBUG)
async def find_xargs(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> XargsBinary:
    request = BinaryPathRequest(
        binary_name="xargs", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xargs file")
    return XargsBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sort` binary", level=LogLevel.DEBUG)
async def find_sort(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> SortBinary:
    request = BinaryPathRequest(binary_name="sort", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sort file")
    return SortBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sh` binary", level=LogLevel.DEBUG)
async def find_sh(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ShBinary:
    request = BinaryPathRequest(binary_name="sh", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sh file")
    return ShBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tr` binary", level=LogLevel.DEBUG)
async def find_tr(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TrBinary:
    request = BinaryPathRequest(binary_name="tr", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tr file")
    return TrBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cksum` binary", level=LogLevel.DEBUG)
async def find_cksum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CksumBinary:
    request = BinaryPathRequest(
        binary_name="cksum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cksum file")
    return CksumBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
