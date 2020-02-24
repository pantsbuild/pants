# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.backend.codegen.wire.java.java_wire_library import JavaWireLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.source.filespec import globs_matches
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import fast_relpath
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class WireGen(NailgunTaskBase, SimpleCodegenTask):

    sources_globs = ("**/*",)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        def wire_jar(name):
            return JarDependency(org="com.squareup.wire", name=name, rev="1.8.0")

        cls.register_jvm_tool(
            register,
            "javadeps",
            classpath=[wire_jar(name="wire-runtime")],
            classpath_spec="//:wire-runtime",
            help="Runtime dependencies for wire-using Java code.",
        )
        cls.register_jvm_tool(register, "wire-compiler", classpath=[wire_jar(name="wire-compiler")])

    @classmethod
    def is_wire_compiler_jar(cls, jar):
        return "com.squareup.wire" == jar.org and "wire-compiler" == jar.name

    def __init__(self, *args, **kwargs):
        """Generates Java files from .proto files using the Wire protobuf compiler."""
        super().__init__(*args, **kwargs)

    def synthetic_target_type(self, target):
        return JavaLibrary

    def is_gentarget(self, target):
        return isinstance(target, JavaWireLibrary)

    def synthetic_target_extra_dependencies(self, target, target_workdir):
        wire_runtime_deps_spec = self.get_options().javadeps
        return self.resolve_deps([wire_runtime_deps_spec])

    def _compute_sources(self, target):
        relative_sources = OrderedSet()
        source_roots = OrderedSet()

        def capture_and_relativize_to_source_root(source):
            source_root = self.context.source_roots.find_by_path(source)
            if not source_root:
                source_root = self.context.source_roots.find(target)
            source_roots.add(source_root.path)
            return fast_relpath(source, source_root.path)

        if target.payload.get_field_value("ordered_sources"):
            # Re-match the filespecs against the sources in order to apply them in the literal order
            # they were specified in.
            filespec = target.globs_relative_to_buildroot()
            excludes = filespec.get("excludes", [])
            for filespec in filespec.get("globs", []):
                sources = [
                    s
                    for s in target.sources_relative_to_buildroot()
                    if globs_matches([s], [filespec], excludes)
                ]
                if len(sources) != 1:
                    raise TargetDefinitionException(
                        target,
                        "With `ordered_sources=True`, expected one match for each file literal, "
                        "but got: {} for literal `{}`.".format(sources, filespec),
                    )
                relative_sources.add(capture_and_relativize_to_source_root(sources[0]))
        else:
            # Otherwise, use the default (unspecified) snapshot ordering.
            for source in target.sources_relative_to_buildroot():
                relative_sources.add(capture_and_relativize_to_source_root(source))
        return relative_sources, source_roots

    def format_args_for_target(self, target, target_workdir):
        """Calculate the arguments to pass to the command line for a single target."""

        args = ["--java_out={0}".format(target_workdir)]

        # Add all params in payload to args

        relative_sources, source_roots = self._compute_sources(target)

        if target.payload.get_field_value("no_options"):
            args.append("--no_options")

        if target.payload.service_writer:
            args.append("--service_writer={}".format(target.payload.service_writer))
            if target.payload.service_writer_options:
                for opt in target.payload.service_writer_options:
                    args.append("--service_writer_opt")
                    args.append(opt)

        registry_class = target.payload.registry_class
        if registry_class:
            args.append("--registry_class={0}".format(registry_class))

        if target.payload.roots:
            args.append("--roots={0}".format(",".join(target.payload.roots)))

        if target.payload.enum_options:
            args.append("--enum_options={0}".format(",".join(target.payload.enum_options)))

        for source_root in source_roots:
            args.append("--proto_path={0}".format(os.path.join(get_buildroot(), source_root)))

        args.extend(relative_sources)
        return args

    def execute_codegen(self, target, target_workdir):
        args = self.format_args_for_target(target, target_workdir)
        if args:
            result = self.runjava(
                classpath=self.tool_classpath("wire-compiler"),
                main="com.squareup.wire.WireCompiler",
                args=args,
                workunit_name="compile",
                workunit_labels=[WorkUnitLabel.TOOL],
            )
            if result != 0:
                raise TaskError("Wire compiler exited non-zero ({0})".format(result))
