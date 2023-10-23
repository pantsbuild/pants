# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Dependencies
from pants.engine.unions import UnionRule
from pants.jvm import classpath
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntries,
    FallibleClasspathEntry,
)
from pants.jvm.jar_tool.jar_tool import JarToolRequest
from pants.jvm.jar_tool.jar_tool import rules as jar_tool_rules
from pants.jvm.shading.rules import ShadedJar, ShadeJarRequest
from pants.jvm.shading.rules import rules as shaded_jar_rules
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    DeployJarDuplicatePolicyField,
    DeployJarExcludeFilesField,
    DeployJarShadingRulesField,
    JvmDependenciesField,
    JvmJdkField,
    JvmMainClassNameField,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployJarFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (
        JvmMainClassNameField,
        JvmJdkField,
        Dependencies,
        OutputPathField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    main_class: JvmMainClassNameField
    output_path: OutputPathField
    dependencies: JvmDependenciesField
    jdk_version: JvmJdkField
    duplicate_policy: DeployJarDuplicatePolicyField
    shading_rules: DeployJarShadingRulesField
    exclude_files: DeployJarExcludeFilesField


class DeployJarClasspathEntryRequest(ClasspathEntryRequest):
    field_sets = (DeployJarFieldSet,)
    # A `deploy_jar` can have a Classpath requested for it, but should not be used as a dependency.
    root_only = True


@rule
async def deploy_jar_classpath(
    request: DeployJarClasspathEntryRequest,
) -> FallibleClasspathEntry:
    if len(request.component.members) > 1:
        # If multiple DeployJar targets were coarsened into a single instance, it's because they
        # formed a cycle among themselves... but at a high level, they shouldn't have dependencies
        # on one another anyway.
        raise Exception(
            "`deploy_jar` targets should not depend on one another:\n"
            f"{request.component.bullet_list()}"
        )
    fallible_entries = await Get(FallibleClasspathEntries, ClasspathDependenciesRequest(request))
    classpath_entries = fallible_entries.if_all_succeeded()
    if classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )
    return FallibleClasspathEntry(
        description=str(request.component),
        result=CompileResult.SUCCEEDED,
        output=ClasspathEntry(EMPTY_DIGEST, dependencies=classpath_entries),
        exit_code=0,
    )


@rule
async def package_deploy_jar(
    jvm: JvmSubsystem,
    field_set: DeployJarFieldSet,
) -> BuiltPackage:
    """
    Constructs a deploy ("fat") JAR file by
    1. Resolving/compiling a Classpath for the `root_address` target,
    2. Creating a deploy jar with a valid ZIP index and deduplicated entries
    3. (optionally) Stripping the jar of all metadata that may cause it to be non-reproducible (https://reproducible-builds.org)
    4. (optionally) Apply shading rules to the bytecode inside the jar file
    """

    if field_set.main_class.value is None:
        raise Exception("Needs a `main` argument")

    #
    # 1. Produce thin JARs containing the transitive classpath
    #

    classpath = await Get(Classpath, Addresses([field_set.address]))
    classpath_digest = await Get(Digest, MergeDigests(classpath.digests()))

    #
    # 2. Use Pants' JAR tool to build a runnable fat JAR
    #

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending="jar"))
    jar_digest = await Get(
        Digest,
        JarToolRequest(
            jar_name=output_filename.name,
            digest=classpath_digest,
            main_class=field_set.main_class.value,
            jars=classpath.args(),
            policies=[
                (rule.pattern, rule.action)
                for rule in field_set.duplicate_policy.value_or_default()
            ],
            skip=field_set.exclude_files.value,
            compress=True,
        ),
    )

    #
    # 3. Strip the JAR from  all non-reproducible metadata if requested so
    #
    if jvm.reproducible_jars:
        jar_digest = await Get(
            Digest,
            StripJarRequest(
                digest=jar_digest,
                filenames=(output_filename.name,),
            ),
        )

    #
    # 4. Apply shading rules
    #
    if field_set.shading_rules.value:
        shaded_jar = await Get(
            ShadedJar,
            ShadeJarRequest(
                path=output_filename,
                digest=jar_digest,
                rules=field_set.shading_rules.value,
                skip_manifest=False,
            ),
        )
        jar_digest = shaded_jar.digest

    prefixed_output_digest = await Get(Digest, AddPrefix(jar_digest, str(output_filename.parent)))
    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(digest=prefixed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        *classpath.rules(),
        *jar_tool_rules(),
        *shaded_jar_rules(),
        UnionRule(PackageFieldSet, DeployJarFieldSet),
        UnionRule(ClasspathEntryRequest, DeployJarClasspathEntryRequest),
    ]
