# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Tuple

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.core.util_rules.system_binaries import (
    AwkBinary,
    BasenameBinary,
    BashBinary,
    BinaryPathRequest,
    BinaryShimsRequest,
    CatBinary,
    ChmodBinary,
    CksumBinary,
    CutBinary,
    DateBinary,
    DdBinary,
    DfBinary,
    DirnameBinary,
    DuBinary,
    ExprBinary,
    FindBinary,
    GzipBinary,
    HeadBinary,
    IdBinary,
    MkdirBinary,
    PwdBinary,
    RmBinary,
    SedBinary,
    ShBinary,
    SortBinary,
    TailBinary,
    TarBinary,
    TestBinary,
    TrBinary,
    WcBinary,
    XargsBinary,
)
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class MakeselfBinaryShimsRequest:
    """Request all the binaries needed to create or run makeself archive.

    Technically, you might need different sets of binaries for creating and running the makeself
    archive, but most of the binaries are the same, so we bundle them all in a single rule for
    simplicity.
    """

    extra_tools: Tuple[str, ...]
    rationale: str


@rule(desc="Find binaries required for makeself", level=LogLevel.DEBUG)
async def get_binaries_required_for_makeself(
    request: MakeselfBinaryShimsRequest,
    shell_setup: ShellSetup.EnvironmentAware,
    awk: AwkBinary,
    basename: BasenameBinary,
    bash: BashBinary,
    cat: CatBinary,
    chmod: ChmodBinary,
    cksum: CksumBinary,
    cut: CutBinary,
    date: DateBinary,
    dd: DdBinary,
    df: DfBinary,
    dirname: DirnameBinary,
    du: DuBinary,
    expr: ExprBinary,
    find: FindBinary,
    gzip: GzipBinary,
    head: HeadBinary,
    id: IdBinary,
    mkdir: MkdirBinary,
    pwd: PwdBinary,
    rm: RmBinary,
    sed: SedBinary,
    sh: ShBinary,
    sort: SortBinary,
    tail: TailBinary,
    tar: TarBinary,
    test: TestBinary,
    tr: TrBinary,
    wc: WcBinary,
    xargs: XargsBinary,
) -> BinaryShimsRequest:
    return BinaryShimsRequest(
        paths=(
            awk,
            basename,
            bash,
            cat,
            chmod,
            cksum,
            cut,
            date,
            dd,
            df,
            dirname,
            du,
            expr,
            find,
            gzip,
            head,
            id,
            mkdir,
            pwd,
            rm,
            sed,
            sh,
            sort,
            tail,
            tar,
            test,
            tr,
            wc,
            xargs,
        ),
        requests=tuple(
            BinaryPathRequest(
                binary_name=binary_name,
                search_path=shell_setup.executable_search_path,
            )
            for binary_name in request.extra_tools
            if binary_name not in BASH_BUILTIN_COMMANDS
        ),
        rationale=request.rationale,
    )


def rules():
    return collect_rules()
