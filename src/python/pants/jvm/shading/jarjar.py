# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.option.option_types import BoolOption
from pants.util.docutil import git_url


class JarJar(JvmToolBase):
    options_scope = "jarjar"
    help = "The Jar Jar Links tool (https://github.com/google/jarjar)"

    default_version = "1.3"
    default_artifacts = ("com.googlecode.jarjar:jarjar:{version}",)
    default_lockfile_resource = (
        "pants.jvm.shading",
        "jarjar.default.lockfile.txt",
    )
    default_lockfile_path = "src/python/pants/jvm/shading/jarjar.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    verbose = BoolOption(default=False, help="Run JarJar in verbose mode.")
    skip_manifest = BoolOption(default=False, help="Skip the processing of the JAR manifest.")


class JarJarGeneratorLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = JarJar.options_scope


@rule
async def generate_jarjar_lockfile_request(
    _: JarJarGeneratorLockfileSentinel, jarjar: JarJar
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(jarjar)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, JarJarGeneratorLockfileSentinel),
    ]
