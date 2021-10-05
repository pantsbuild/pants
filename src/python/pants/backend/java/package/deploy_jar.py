# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import shlex
import textwrap
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.java.classpath import Classpath
from pants.backend.java.target_types import JvmMainClassName
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.archive import ZipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


_JAVA_MANIFEST_FILENAME = "META-INF/MANIFEST.MF"
_PANTS_MANIFEST_PARTIAL_JAR_FILENAME = "pants_manifest_only.notajar"
_PANTS_CAT_AND_REPAIR_ZIP_FILENAME = "_cat_and_repair_zip_files.sh"


@dataclass(frozen=True)
class DeployJarFieldSet(PackageFieldSet):
    required_fields = (
        JvmMainClassName,
        Dependencies,
    )

    main_class: JvmMainClassName
    output_path: OutputPathField
    dependencies: Dependencies


@rule
async def package_deploy_jar(
    bash: BashBinary,
    zip: ZipBinary,
    field_set: DeployJarFieldSet,
) -> BuiltPackage:
    """
    Constructs a deploy ("fat") JAR file (currently from Java sources only) by
    1. Resolving/compiling a classpath for the `root_address` target,
    2. Producing a ZIP file containing _only_ the JAR manifest file for the `main_class`
    3. Creating a deploy jar with a broken ZIP index by concatenating all dependency JARs together,
       followed by the thin JAR we created
    4. Using the unix `zip` utility's repair function to fix the broken fat jar
    """

    if field_set.main_class.value is None:
        raise Exception("Needs a `main` argument")

    #
    # 1. Produce a thin JAR containing our first-party sources and other runtime dependencies
    #

    dependencies = await Get(Addresses, DependenciesRequest(field_set.dependencies))
    classpath = await Get(Classpath, Addresses, dependencies)

    #
    # 2. Produce JAR manifest, and output to a ZIP file that can be included with the JARs
    #

    main_class = field_set.main_class.value

    manifest_content = FileContent(
        _JAVA_MANIFEST_FILENAME,
        # NB: we're joining strings with newlines, becuase the JAR manfiest format
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

    manifest_jar_input_digest = await Get(Digest, CreateDigest([manifest_content]))
    manifest_jar_result = await Get(
        ProcessResult,
        Process(
            argv=[
                zip.path,
                _PANTS_MANIFEST_PARTIAL_JAR_FILENAME,
                _JAVA_MANIFEST_FILENAME,
            ],
            description="Build partial JAR containing manifest file",
            input_digest=manifest_jar_input_digest,
            output_files=[_PANTS_MANIFEST_PARTIAL_JAR_FILENAME],
        ),
    )

    manifest_jar = manifest_jar_result.output_digest

    #
    # 3/4. Create broken deploy JAR, then repair it with `zip -FF`
    #

    # NB. Concatenating multiple ZIP files produces a zip file that is _mostly_ safe to
    # be distributed (it can be fixed with `-FF`), so that's how we construct our fat JAR
    # without exploding the files to disk.
    #
    # `ZIP` files are extracted top-to-bottom and archives can have duplicate names
    # (e.g. `META-INF/MANIFEST.MF`). In the case of a `JAR` file, the JVM will understand the
    # last file with that file name to be the actual one. Therefore, our thin JAR needs to be
    # appear at the end of the file for (in particular) our manifest to take precedence.
    # If there are duplicate classnames at a given package address fat JARs, then
    # behaviour will be non-deterministic. Sorry!  --chrisjrn

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending="jar"))
    input_filenames = " ".join(shlex.quote(i) for i in classpath.classpath_entries())
    _PANTS_BROKEN_DEPLOY_JAR = "pants_broken_deploy_jar.notajar"
    cat_and_repair_script = FileContent(
        _PANTS_CAT_AND_REPAIR_ZIP_FILENAME,
        # Using POSIX location/arg format for `cat`. If this gets more complicated, refactor.
        textwrap.dedent(
            f"""
            set -e
            /bin/cat {input_filenames} {_PANTS_MANIFEST_PARTIAL_JAR_FILENAME} > {_PANTS_BROKEN_DEPLOY_JAR}
            {zip.path} -FF {_PANTS_BROKEN_DEPLOY_JAR} --out {output_filename.name}
            """
        ).encode("utf-8"),
    )

    cat_and_repair_script_digest = await Get(Digest, CreateDigest([cat_and_repair_script]))
    broken_deploy_jar_inputs_digest = await Get(
        Digest,
        MergeDigests([classpath.content.digest, cat_and_repair_script_digest, manifest_jar]),
    )

    cat_and_repair = await Get(
        ProcessResult,
        Process(
            argv=[bash.path, _PANTS_CAT_AND_REPAIR_ZIP_FILENAME],
            input_digest=broken_deploy_jar_inputs_digest,
            output_files=[output_filename.name],
            description="Assemble combined JAR file",
        ),
    )

    renamed_output_digest = await Get(
        Digest, AddPrefix(cat_and_repair.output_digest, str(output_filename.parent))
    )

    artifact = BuiltPackageArtifact(relpath=str(output_filename))

    return BuiltPackage(digest=renamed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DeployJarFieldSet),
    ]
