# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import shlex
import textwrap

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.native_engine import AddPrefix
from pants.engine.process import BashBinary, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JvmProcess
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@rule(level=LogLevel.DEBUG)
async def create_deploy_jar_run_request(
    field_set: DeployJarFieldSet,
    bash: BashBinary,
) -> RunRequest:

    main_class = field_set.main_class.value
    assert main_class is not None

    package = await Get(BuiltPackage, DeployJarFieldSet, field_set)
    assert len(package.artifacts) == 1
    jar_path = package.artifacts[0].relpath
    assert jar_path is not None

    proc = await Get(
        Process,
        JvmProcess(
            classpath_entries=[jar_path],
            argv=(main_class,),
            input_digest=package.digest,
            description=f"Run {main_class}.main(String[])",
            use_nailgun=False,
        ),
    )

    support_digests = await MultiGet(
        Get(Digest, AddPrefix(digest, prefix))
        for prefix, digest in proc.immutable_input_digests.items()
    )

    bloop = textwrap.dedent(
        f"""\
    set -x
    echo `dirname $0`
    cd `dirname $0`
    ls -r
    {shlex.join(proc.argv)}
    """
    )

    logger.warning("%s", bloop)
    relapath = "pingle.sh"
    relativizer = await Get(Digest, CreateDigest([FileContent(relapath, bloop.encode("utf-8"))]))

    request_digest = await Get(
        Digest,
        MergeDigests(
            [
                proc.input_digest,
                *support_digests,
                relativizer,
            ]
        ),
    )

    args = [bash.path, f"{{chroot}}/{relapath}"]
    logger.warning("%s", f"{args=}")

    return RunRequest(
        digest=request_digest,
        args=args,
        extra_env=proc.env,
        append_only_caches=proc.append_only_caches,
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, DeployJarFieldSet)]
