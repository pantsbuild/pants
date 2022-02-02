# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import shlex
import textwrap

from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.native_engine import AddPrefix
from pants.engine.process import BashBinary, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import JvmProcess
from pants.jvm.package.deploy_jar import DeployJarClasspathEntryRequest, DeployJarFieldSet
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@rule(level=LogLevel.DEBUG)
async def create_deploy_jar_run_request(
    field_set: DeployJarFieldSet,
    bash: BashBinary,
) -> RunRequest:
    """transitive_targets = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )"""

    coarsened_targets = await Get(CoarsenedTargets, Addresses([field_set.address]))
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    item = await Get(
        ClasspathEntry,
        DeployJarClasspathEntryRequest(component=coarsened_targets[0], resolve=resolve),
    )

    assert (
        len(item.dependencies) == 1
    )  # Deploy JAR requests should only produce a single deploy JAR

    main_class = field_set.main_class.value
    assert main_class is not None

    out_jar: ClasspathEntry = next(iter(item.dependencies))

    proc = await Get(
        Process,
        JvmProcess(
            classpath_entries=out_jar.filenames,
            argv=(main_class,),
            input_digest=out_jar.digest,
            description=f"Run {out_jar.filenames[0]}",
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

    return RunRequest(digest=request_digest, args=args, extra_env=proc.env)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, DeployJarFieldSet)]
