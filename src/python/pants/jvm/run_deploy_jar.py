# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging

from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunRequest
from pants.core.util_rules.system_binaries import rules as system_binaries_rules
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.package.deploy_jar import DeployJarFieldSet
from pants.jvm.package.deploy_jar import rules as deploy_jar_rules
from pants.jvm.run import _post_process_jvm_process
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@rule(level=LogLevel.DEBUG)
async def create_deploy_jar_run_request(
    field_set: DeployJarFieldSet,
) -> RunRequest:
    jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(field_set.jdk_version))

    main_class = field_set.main_class.value
    assert main_class is not None

    package = await Get(BuiltPackage, DeployJarFieldSet, field_set)
    assert len(package.artifacts) == 1
    jar_path = package.artifacts[0].relpath
    assert jar_path is not None

    proc = await Get(
        Process,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{{chroot}}/{jar_path}"],
            argv=(main_class,),
            input_digest=package.digest,
            description=f"Run {main_class}.main(String[])",
            use_nailgun=False,
        ),
    )

    return _post_process_jvm_process(proc, jdk)


def rules():
    return [
        *collect_rules(),
        *DeployJarFieldSet.rules(),
        *deploy_jar_rules(),
        *system_binaries_rules(),
        *jdk_rules(),
        *classpath_rules(),
    ]
