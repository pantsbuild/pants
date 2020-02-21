# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException


class JavaThriftLibrary(JvmTarget):
    """A Java library generated from Thrift IDL files.

    :API: public
    """

    # TODO(John Sirois): Tasks should register the values they support in a plugin-registration goal.
    # In general a plugin will contribute a target and a task, but in this case we have a shared
    # target that can be used by at least 2 tasks - ThriftGen and ScroogeGen.  This is likely not
    # uncommon (gcc & clang) so the arrangement needs to be cleaned up and supported well.
    _COMPILERS = frozenset({"thrift", "scrooge"})

    def __init__(
        self,
        compiler=None,
        language=None,
        namespace_map=None,
        thrift_linter_strict=None,
        default_java_namespace=None,
        include_paths=None,
        compiler_args=None,
        **kwargs
    ):
        """
        :API: public

        :param compiler: The compiler used to compile the thrift files. The default is defined in
          the global options under ``--thrift-default-compiler``.
        :param language: The language used to generate the output files. The default is defined in
          the global options under ``--thrift-default-language``.
        :param namespace_map: An optional dictionary of namespaces to remap {old: new}
        :param thrift_linter_strict: If True, fail if thrift linter produces any warnings.
        :param default_java_namespace: The namespace used for Java generated code when a Java
          namespace is not explicitly specified in the IDL. The default is defined in the global
          options under ``--thrift-default-default-java-namespace``.
        :param compiler_args: Extra arguments to the compiler.
        """
        super().__init__(**kwargs)

        def check_value_for_arg(arg, value, values):
            if value and value not in values:
                raise TargetDefinitionException(
                    self,
                    "{} may only be set to {} ('{}' not valid)".format(
                        arg, ", or ".join(map(repr, values)), value
                    ),
                )
            return value

        # The following fields are only added to the fingerprint via FingerprintStrategy when their
        # values impact the outcome of the task.  See JavaThriftLibraryFingerprintStrategy.
        self._compiler = check_value_for_arg("compiler", compiler, self._COMPILERS)
        self._language = language

        self.namespace_map = namespace_map
        self.thrift_linter_strict = thrift_linter_strict
        self._default_java_namespace = default_java_namespace
        self._include_paths = include_paths
        self._compiler_args = compiler_args

    @property
    def compiler(self):
        return self._compiler

    @property
    def language(self):
        return self._language

    @property
    def compiler_args(self):
        return self._compiler_args

    @property
    def default_java_namespace(self):
        return self._default_java_namespace

    @property
    def include_paths(self):
        return self._include_paths
