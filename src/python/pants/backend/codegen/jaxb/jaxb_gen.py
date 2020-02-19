# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.backend.codegen.jaxb.jaxb_library import JaxbLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.task.simple_codegen_task import SimpleCodegenTask


class JaxbGen(SimpleCodegenTask, NailgunTask):
    """Generates java source files from jaxb schema (.xsd)."""

    _XJC_MAIN = "com.sun.tools.xjc.Driver"
    _XML_BIND_VERSION = "2.3.0"

    sources_globs = ("**/*",)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        cls.register_jvm_tool(
            register,
            "xjc",
            classpath=[
                JarDependency(org="com.sun.xml.bind", name="jaxb-core", rev=cls._XML_BIND_VERSION),
                JarDependency(org="com.sun.xml.bind", name="jaxb-impl", rev=cls._XML_BIND_VERSION),
                JarDependency(org="com.sun.xml.bind", name="jaxb-xjc", rev=cls._XML_BIND_VERSION),
                JarDependency(org="com.sun.activation", name="javax.activation", rev="1.2.0"),
                JarDependency(org="javax.xml.bind", name="jaxb-api", rev=cls._XML_BIND_VERSION),
            ],
            main=cls._XJC_MAIN,
        )

    def __init__(self, *args, **kwargs):
        """
        :param context: inherited parameter from Task
        :param workdir: inherited parameter from Task
        """
        super().__init__(*args, **kwargs)
        self.set_distribution(jdk=True)
        self.gen_langs = set()
        lang = "java"
        if self.context.products.isrequired(lang):
            self.gen_langs.add(lang)

    def synthetic_target_type(self, target):
        return JavaLibrary

    def is_gentarget(self, target):
        return isinstance(target, JaxbLibrary)

    def execute_codegen(self, target, target_workdir):
        if not isinstance(target, JaxbLibrary):
            raise TaskError(
                'Invalid target type "{class_type}" (expected JaxbLibrary)'.format(
                    class_type=type(target).__name__
                )
            )

        for source in target.sources_relative_to_buildroot():
            path_to_xsd = source
            output_package = target.package

            if output_package is None:
                output_package = self._guess_package(source)
            output_package = self._correct_package(output_package)

            # NB(zundel): The -no-header option keeps it from writing a timestamp, making the
            # output non-deterministic.  See https://github.com/pantsbuild/pants/issues/1786
            args = ["-p", output_package, "-d", target_workdir, "-no-header", path_to_xsd]
            result = self.runjava(
                classpath=self.tool_classpath("xjc"),
                main=self._XJC_MAIN,
                jvm_options=self.get_options().jvm_options,
                args=args,
                workunit_name="xjc",
                workunit_labels=[WorkUnitLabel.TOOL],
            )

            if result != 0:
                raise TaskError("xjc ... exited non-zero ({code})".format(code=result))

    @classmethod
    def _guess_package(self, path):
        """Used in execute_codegen to actually invoke the compiler with the proper arguments, and in
        _sources_to_be_generated to declare what the generated files will be."""
        supported_prefixes = (
            "com",
            "org",
            "net",
        )
        package = ""
        slash = path.rfind(os.path.sep)
        prefix_with_slash = max(
            path.rfind(os.path.join("", prefix, "")) for prefix in supported_prefixes
        )
        if prefix_with_slash < 0:
            package = path[:slash]
        elif prefix_with_slash >= 0:
            package = path[prefix_with_slash:slash]
        package = package.replace(os.path.sep, " ")
        package = package.strip().replace(" ", ".")
        return package

    @classmethod
    def _correct_package(self, package):
        package = package.replace("/", ".")
        package = re.sub(r"^\.+", "", package)
        package = re.sub(r"\.+$", "", package)
        if re.search(r"\.{2,}", package) is not None:
            raise ValueError("Package name cannot have consecutive periods! ({})".format(package))
        return package
