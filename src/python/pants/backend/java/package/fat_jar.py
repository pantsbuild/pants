# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import textwrap
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.java.compile.javac import (
    CompileJavaSourceRequest,
    CompileResult,
    FallibleCompiledClassfiles,
)
from pants.backend.java.target_types import JavaSourceField, JvmMainClassName, JvmRootClassAddress
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Snapshot
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FatJarFieldSet(PackageFieldSet):
    required_fields = (
        JvmMainClassName,
        JvmRootClassAddress,
    )

    main_class: JvmMainClassName
    root_address: JvmRootClassAddress
    output_path: OutputPathField


@rule
async def package_fat_jar(
    bash: BashBinary,
    field_set: FatJarFieldSet,
) -> BuiltPackage:
    """
    Constructs a "fat" JAR file (currently from Java sources only) by
    1. compiling all Java sources
    2. building a JAR containing all of those built class files
    3. creating a fat jar with a broken ZIP index by concatenating all dependency JARs together,
       followed by the thin JAR we created
    4. using the unix `zip` utility's repair function to fix the broken fat jar
    """

    if field_set.root_address.value is None:
        raise Exception("Needs a `root_address` argument")

    if field_set.main_class.value is None:
        raise Exception("Needs a `main` argument")

    root_class_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(field_set.root_address.value, relative_to=field_set.address.spec_path),
    )

    # 1. Collect Java source files and compile them all
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([root_class_address])
    )

    sources_to_compile = await Get(
        CoarsenedTargets,
        Addresses(
            tgt.address for tgt in transitive_targets.closure if tgt.has_field(JavaSourceField)
        ),
    )

    javac_request_gets = [
        Get(FallibleCompiledClassfiles, CompileJavaSourceRequest(tgt)) for tgt in sources_to_compile
    ]
    fallible_class_files = await MultiGet(javac_request_gets)

    failed = [i for i in fallible_class_files if i.result == CompileResult.FAILED]
    if failed:
        raise Exception(failed[0].stderr)

    # TODO: better handle `i.output is None` case
    class_files = [i.output for i in fallible_class_files if i.output is not None]
    compiled_class_files_digest = await Get(Digest, MergeDigests(i.digest for i in class_files))
    compiled_class_files_snapshot = await Get(Snapshot, Digest, compiled_class_files_digest)

    # 2. Produce thin JAR
    main_class = field_set.main_class.value

    manifest_content = FileContent(
        "META-INF/MANIFEST.MF",
        # NB(chrisjrn): we're joining strings with newlines, becuase the JAR manfiest format
        # needs precise indentation, and _cannot_ start with a blank line. `dedent` seriously
        # messes up those requirements.
        "\n".join(
            [
                "Manifest-Version: 1.0",
                f"Main-Class: {main_class}",
                "",  # THIS BLANK LINE WILL BREAK EVERYTHING IF DELETED. DON'T DELETE IT.
            ]
        ).encode("utf-8"),
    )

    manifest_digest = await Get(Digest, CreateDigest([manifest_content]))
    thin_jar_inputs = await Get(
        Digest, MergeDigests([compiled_class_files_digest, manifest_digest])
    )

    thin_jar_result = await Get(
        ProcessResult,
        Process(
            argv=[
                "/usr/bin/zip",
                "pants_thin_jar.jar",
                *compiled_class_files_snapshot.files + ("META-INF/MANIFEST.MF",),
            ],
            description="Build thin JAR file.",
            input_digest=thin_jar_inputs,
            output_files=["pants_thin_jar.jar"],
        ),
    )

    logger.info(thin_jar_result.stdout.decode())
    logger.info(thin_jar_result.stderr.decode())

    thin_jar = thin_jar_result.output_digest

    # 3. Create broken fat JAR
    lockfile_requests = [
        Get(
            CoursierResolvedLockfile,
            CoursierLockfileForTargetRequest(
                Targets(CompileJavaSourceRequest(tgt).component.members)
            ),
        )
        for tgt in sources_to_compile
    ]
    lockfiles = await MultiGet(lockfile_requests)

    materialized_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="coursier",
            lockfiles=lockfiles,
        ),
    )

    cat_script = FileContent(
        "_cat_zip_files.sh",
        textwrap.dedent(
            f"""
            /bin/cat {" ".join(materialized_classpath._reified_filenames())} pants_thin_jar.jar > pants_broken_fat_jar.jar
            """
        ).encode("utf-8"),
    )

    cat_script_digest = await Get(Digest, CreateDigest([cat_script]))
    broken_fat_jar_inputs_digest = await Get(
        Digest, MergeDigests([materialized_classpath.digest, cat_script_digest, thin_jar])
    )

    cat = await Get(
        ProcessResult,
        Process(
            argv=[bash.path, "_cat_zip_files.sh"],
            input_digest=broken_fat_jar_inputs_digest,
            output_files=["pants_broken_fat_jar.jar"],
            description="Assemble combined JAR file for postprocessing",
        ),
    )

    broken_fat_jar_digest = cat.output_digest

    # 4. Correct the fat JAR
    output_filename = PurePath(field_set.output_path.value_or_default(file_ending="jar"))
    fix_zip = await Get(
        ProcessResult,
        Process(
            argv=["/usr/bin/zip", "-FF", "pants_broken_fat_jar.jar", "--out", output_filename.name],
            input_digest=broken_fat_jar_digest,
            description="Post-process combined JAR file",
            output_files=[output_filename.name],
        ),
    )

    renamed_output_digest = await Get(
        Digest, AddPrefix(fix_zip.output_digest, str(output_filename.parent))
    )

    artifact = BuiltPackageArtifact(relpath=str(output_filename))

    return BuiltPackage(digest=renamed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, FatJarFieldSet),
    ]
