# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TargetDefinitionException


# TODO: Currently the injected runtime deps are specified by the --deps option defined in the
# base class, which can only take specs (as it must also work for Python).
# However it would be more convenient if this task could provide a default hard-coded
# JarDependency via register_jvm_tool(), as then users happy with the default wouldn't have
# to have a BUILD file entry for the default spec to point to.
class ApacheThriftJavaGen(ApacheThriftGenBase):
    """Generate Java source files from thrift IDL files."""

    gentarget_type = JavaThriftLibrary
    thrift_generator = "java"

    _COMPILER = "thrift"

    sources_globs = ("**/*",)

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ThriftDefaults,)

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("ApacheThriftJavaGen", 2)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thrift_defaults = ThriftDefaults.global_instance()

    def synthetic_target_type(self, target):
        return JavaLibrary

    def is_gentarget(self, target):
        return (
            super().is_gentarget(target)
            and self._thrift_defaults.compiler(target) == self._COMPILER
        )

    def _validate(self, target):
        # TODO: Fix ThriftDefaults to only pertain to scrooge (see TODO there) and then
        # get rid of this spurious validation.
        if self._thrift_defaults.language(target) != self.thrift_generator:
            raise TargetDefinitionException(
                target,
                "Compiler {} supports only language={}.".format(
                    self._COMPILER, self.thrift_generator
                ),
            )

    def execute_codegen(self, target, target_workdir):
        self._validate(target)
        super().execute_codegen(target, target_workdir)
