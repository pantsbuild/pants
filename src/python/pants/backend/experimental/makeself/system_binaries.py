from pants.core.util_rules.system_binaries import (
    SEARCH_PATHS,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
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
async def find_dirname() -> DirnameBinary:
    request = BinaryPathRequest(binary_name="dirname", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dirname file")
    return DirnameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `id` binary", level=LogLevel.DEBUG)
async def find_id() -> IdBinary:
    request = BinaryPathRequest(binary_name="id", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="id file")
    return IdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `awk` binary", level=LogLevel.DEBUG)
async def find_awk() -> AwkBinary:
    request = BinaryPathRequest(binary_name="awk", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="awk file")
    return AwkBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `basename` binary", level=LogLevel.DEBUG)
async def find_basename() -> BasenameBinary:
    request = BinaryPathRequest(binary_name="basename", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="basename file")
    return BasenameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cut` binary", level=LogLevel.DEBUG)
async def find_cut() -> CutBinary:
    request = BinaryPathRequest(binary_name="cut", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cut file")
    return CutBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `df` binary", level=LogLevel.DEBUG)
async def find_df() -> DfBinary:
    request = BinaryPathRequest(binary_name="df", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="df file")
    return DfBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `expr` binary", level=LogLevel.DEBUG)
async def find_expr() -> ExprBinary:
    request = BinaryPathRequest(binary_name="expr", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="expr file")
    return ExprBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gzip` binary", level=LogLevel.DEBUG)
async def find_gzip() -> GzipBinary:
    request = BinaryPathRequest(binary_name="gzip", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gzip file")
    return GzipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `head` binary", level=LogLevel.DEBUG)
async def find_head() -> HeadBinary:
    request = BinaryPathRequest(binary_name="head", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="head file")
    return HeadBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sed` binary", level=LogLevel.DEBUG)
async def find_sed() -> SedBinary:
    request = BinaryPathRequest(binary_name="sed", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sed file")
    return SedBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tail` binary", level=LogLevel.DEBUG)
async def find_tail() -> TailBinary:
    request = BinaryPathRequest(binary_name="tail", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tail file")
    return TailBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `wc` binary", level=LogLevel.DEBUG)
async def find_wc() -> WcBinary:
    request = BinaryPathRequest(binary_name="wc", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="wc file")
    return WcBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `find` binary", level=LogLevel.DEBUG)
async def find_find() -> FindBinary:
    request = BinaryPathRequest(binary_name="find", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="find file")
    return FindBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `md5sum` binary", level=LogLevel.DEBUG)
async def find_md5sum() -> Md5sumBinary:
    request = BinaryPathRequest(binary_name="md5sum", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="md5sum file")
    return Md5sumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `dd` binary", level=LogLevel.DEBUG)
async def find_dd() -> DdBinary:
    request = BinaryPathRequest(binary_name="dd", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dd file")
    return DdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `test` binary", level=LogLevel.DEBUG)
async def find_test() -> TestBinary:
    request = BinaryPathRequest(binary_name="test", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="test file")
    return TestBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `pwd` binary", level=LogLevel.DEBUG)
async def find_pwd() -> PwdBinary:
    request = BinaryPathRequest(binary_name="pwd", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="pwd file")
    return PwdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xz` binary", level=LogLevel.DEBUG)
async def find_xz() -> XzBinary:
    request = BinaryPathRequest(binary_name="xz", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xz file")
    return XzBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gpg` binary", level=LogLevel.DEBUG)
async def find_gpg() -> GpgBinary:
    request = BinaryPathRequest(binary_name="gpg", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gpg file")
    return GpgBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `base64` binary", level=LogLevel.DEBUG)
async def find_base64() -> Base64Binary:
    request = BinaryPathRequest(binary_name="base64", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="base64 file")
    return Base64Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip2` binary", level=LogLevel.DEBUG)
async def find_bzip2() -> Bzip2Binary:
    request = BinaryPathRequest(binary_name="bzip2", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip2 file")
    return Bzip2Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip3` binary", level=LogLevel.DEBUG)
async def find_bzip3() -> Bzip3Binary:
    request = BinaryPathRequest(binary_name="bzip3", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip3 file")
    return Bzip3Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lz4` binary", level=LogLevel.DEBUG)
async def find_lz4() -> Lz4Binary:
    request = BinaryPathRequest(binary_name="lz4", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lz4 file")
    return Lz4Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lzop` binary", level=LogLevel.DEBUG)
async def find_lzop() -> LzopBinary:
    request = BinaryPathRequest(binary_name="lzop", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lzop file")
    return LzopBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `zstd` binary", level=LogLevel.DEBUG)
async def find_zstd() -> ZstdBinary:
    request = BinaryPathRequest(binary_name="zstd", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="zstd file")
    return ZstdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `shasum` binary", level=LogLevel.DEBUG)
async def find_shasum() -> ShasumBinary:
    request = BinaryPathRequest(binary_name="shasum", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="shasum file")
    return ShasumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `date` binary", level=LogLevel.DEBUG)
async def find_date() -> DateBinary:
    request = BinaryPathRequest(binary_name="date", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="date file")
    return DateBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `rm` binary", level=LogLevel.DEBUG)
async def find_rm() -> RmBinary:
    request = BinaryPathRequest(binary_name="rm", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="rm file")
    return RmBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `du` binary", level=LogLevel.DEBUG)
async def find_du() -> DuBinary:
    request = BinaryPathRequest(binary_name="du", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="du file")
    return DuBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xargs` binary", level=LogLevel.DEBUG)
async def find_xargs() -> XargsBinary:
    request = BinaryPathRequest(binary_name="xargs", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xargs file")
    return XargsBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sort` binary", level=LogLevel.DEBUG)
async def find_sort() -> SortBinary:
    request = BinaryPathRequest(binary_name="sort", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sort file")
    return SortBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sh` binary", level=LogLevel.DEBUG)
async def find_sh() -> ShBinary:
    request = BinaryPathRequest(binary_name="sh", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sh file")
    return ShBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tr` binary", level=LogLevel.DEBUG)
async def find_tr() -> TrBinary:
    request = BinaryPathRequest(binary_name="tr", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tr file")
    return TrBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cksum` binary", level=LogLevel.DEBUG)
async def find_cksum() -> CksumBinary:
    request = BinaryPathRequest(binary_name="cksum", search_path=SEARCH_PATHS)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cksum file")
    return CksumBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
