# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import tempfile
from collections import defaultdict, namedtuple

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized_method, memoized_property
from pants.util.ordered_set import OrderedSet

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import (
    JavaThriftLibraryFingerprintStrategy,
)
from pants.contrib.scrooge.tasks.thrift_util import calculate_include_paths


class ScroogeGen(SimpleCodegenTask, NailgunTask):

    DepInfo = namedtuple("DepInfo", ["service", "structs"])
    PartialCmd = namedtuple(
        "PartialCmd",
        ["language", "namespace_map", "default_java_namespace", "include_paths", "compiler_args"],
    )

    sources_globs = ("**/*",)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--verbose", type=bool, help="Emit verbose output.")
        register("--strict", fingerprint=True, type=bool, help="Enable strict compilation.")
        register(
            "--service-deps",
            default={},
            advanced=True,
            type=dict,
            help="A map of language to targets to add as dependencies of "
            "synthetic thrift libraries that contain services.",
        )
        register(
            "--structs-deps",
            default={},
            advanced=True,
            type=dict,
            help="A map of language to targets to add as dependencies of "
            "synthetic thrift libraries that contain structs.",
        )
        register(
            "--service-exports",
            default={},
            advanced=True,
            type=dict,
            help="A map of language to targets to add as exports of "
            "synthetic thrift libraries that contain services.",
        )
        register(
            "--structs-exports",
            default={},
            advanced=True,
            type=dict,
            help="A map of language to targets to add as exports of "
            "synthetic thrift libraries that contain structs.",
        )
        register(
            "--target-types",
            default={"scala": "scala_library", "java": "java_library", "android": "java_library"},
            advanced=True,
            type=dict,
            help="Registered target types.",
        )
        register(
            "--unchecked-compiler-args",
            advanced=True,
            type=list,
            default=["--java-passthrough"],
            help="Don't fail if these options are different between targets."
            "Usually, Scrooge requires all targets in the dependency tree to"
            "have the same compiler options. However, discrepancies in options"
            "specified in this list will not cause the compiler to fail.",
        )
        cls.register_jvm_tool(register, "scrooge-gen")

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ThriftDefaults,)

    @classmethod
    def product_types(cls):
        return ["java", "scala"]

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("ScroogeGen", 3)]

    @classmethod
    def get_fingerprint_strategy(cls):
        return JavaThriftLibraryFingerprintStrategy(ThriftDefaults.global_instance())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thrift_defaults = ThriftDefaults.global_instance()
        self._depinfo = None

    # TODO(benjy): Use regular os-located tmpfiles, as we do everywhere else.
    def _tempname(self):
        # don't assume the user's cwd is buildroot
        pants_workdir = self.get_options().pants_workdir
        tmp_dir = os.path.join(pants_workdir, "tmp")
        safe_mkdir(tmp_dir)
        fd, path = tempfile.mkstemp(dir=tmp_dir, prefix="")
        os.close(fd)
        return path

    def _resolve_deps(self, depmap):
        """Given a map of gen-key=>address specs, resolves the address specs into references."""
        deps = defaultdict(lambda: OrderedSet())
        for category, depspecs in depmap.items():
            dependencies = deps[category]
            for depspec in depspecs:
                dep_address = Address.parse(depspec)
                try:
                    self.context.build_graph.maybe_inject_address_closure(dep_address)
                    dependencies.add(self.context.build_graph.get_target(dep_address))
                except AddressLookupError as e:
                    raise AddressLookupError(f"{e}\n  referenced from {self.options_scope} scope")
        return deps

    def _validate_language(self, target):
        language = self._thrift_defaults.language(target)
        if language not in self._registered_language_aliases():
            raise TargetDefinitionException(
                target,
                f"language {language} not supported: expected one of {list(self._registered_language_aliases().keys())}.",
            )
        return language

    @memoized_method
    def _registered_language_aliases(self):
        return self.get_options().target_types

    @memoized_method
    def _target_type_for_language(self, language):
        alias_for_lang = self._registered_language_aliases()[language]
        registered_aliases = self.context.build_configuration.registered_aliases()
        target_types = registered_aliases.target_types_by_alias.get(alias_for_lang, None)
        if not target_types:
            raise TaskError(
                f"Registered target type `{alias_for_lang}` for language `{language}` does not exist!"
            )
        if len(target_types) > 1:
            raise TaskError(f"More than one target type registered for language `{language}`")
        return next(iter(target_types))

    def execute_codegen(self, target, target_workdir):
        self._validate_compiler_configs(target)
        self._must_have_sources(target)

        namespace_map = self._thrift_defaults.namespace_map(target)
        partial_cmd = self.PartialCmd(
            language=self._validate_language(target),
            namespace_map=tuple(sorted(namespace_map.items())) if namespace_map else (),
            default_java_namespace=self._thrift_defaults.default_java_namespace(target),
            include_paths=target.include_paths,
            compiler_args=(self._thrift_defaults.compiler_args(target)),
        )

        self.gen(partial_cmd, target, target_workdir)

    def gen(self, partial_cmd, target, target_workdir):
        import_paths = calculate_include_paths([target], self.is_gentarget)

        args = list(partial_cmd.compiler_args)

        if partial_cmd.default_java_namespace:
            args.extend(["--default-java-namespace", partial_cmd.default_java_namespace])

        for import_path in import_paths:
            args.extend(["--import-path", import_path])

        args.extend(["--language", partial_cmd.language])

        for lhs, rhs in partial_cmd.namespace_map:
            args.extend(["--namespace-map", f"{lhs}={rhs}"])

        args.extend(["--dest", target_workdir])

        if not self.get_options().strict:
            args.append("--disable-strict")

        if partial_cmd.include_paths:
            for include_path in partial_cmd.include_paths:
                args.extend(["--include-path", include_path])

        if self.get_options().verbose:
            args.append("--verbose")

        gen_file_map_path = os.path.relpath(self._tempname())
        args.extend(["--gen-file-map", gen_file_map_path])

        args.extend(target.sources_relative_to_buildroot())

        classpath = self.tool_classpath("scrooge-gen")
        jvm_options = list(self.get_options().jvm_options)
        jvm_options.append("-Dfile.encoding=UTF-8")
        returncode = self.runjava(
            classpath=classpath,
            main="com.twitter.scrooge.Main",
            jvm_options=jvm_options,
            args=args,
            workunit_name="scrooge-gen",
        )
        if 0 != returncode:
            raise TaskError(f"Scrooge compiler exited non-zero for {target} ({returncode})")

    @staticmethod
    def _declares_exception(source):
        # ideally we'd use more sophisticated parsing
        exception_parser = re.compile(r"^\s*exception\s+(?:[^\s{]+)")
        return ScroogeGen._has_declaration(source, exception_parser)

    @staticmethod
    def _declares_service(source):
        # ideally we'd use more sophisticated parsing
        service_parser = re.compile(r"^\s*service\s+(?:[^\s{]+)")
        return ScroogeGen._has_declaration(source, service_parser)

    @staticmethod
    def _has_declaration(source, regex):
        source_path = os.path.join(get_buildroot(), source)
        with open(source_path, "r") as thrift:
            return any(line for line in thrift if regex.search(line))

    def parse_gen_file_map(self, gen_file_map_path, outdir):
        d = defaultdict(set)
        with safe_open(gen_file_map_path, "r") as deps:
            for dep in deps:
                src, cls = dep.strip().split("->")
                src = os.path.relpath(src.strip())
                cls = os.path.relpath(cls.strip(), outdir)
                d[src].add(cls)
        return d

    def is_gentarget(self, target):
        if not isinstance(target, JavaThriftLibrary):
            return False

        # We only handle requests for 'scrooge' compilation and not, for example 'thrift', aka the
        # Apache thrift compiler
        return self._thrift_defaults.compiler(target) == "scrooge"

    _ValidateCompilerConfig = namedtuple(
        "ValidateCompilerConfig", ["language", "compiler", "compiler_args"]
    )

    def _validate_compiler_configs(self, target):
        def filter_unchecked_compiler_args(tgt):
            # Filter out args that exist in the unchecked list from the list of compiler args.
            return [
                args
                for args in self._thrift_defaults.compiler_args(tgt)
                if args not in self.get_options().unchecked_compiler_args
            ]

        def compiler_config(tgt):
            return self._ValidateCompilerConfig(
                language=self._thrift_defaults.language(tgt),
                compiler=self._thrift_defaults.compiler(tgt),
                compiler_args=filter_unchecked_compiler_args(tgt),
            )

        mismatched_compiler_configs = defaultdict(set)
        mycompilerconfig = compiler_config(target)

        def collect(dep):
            if mycompilerconfig != compiler_config(dep):
                mismatched_compiler_configs[target].add(dep)

        target.walk(collect, predicate=lambda t: isinstance(t, JavaThriftLibrary))

        if mismatched_compiler_configs:
            msg = [
                "Thrift dependency trees must be generated with a uniform compiler configuration.\n\n"
            ]
            for tgt in sorted(mismatched_compiler_configs.keys()):
                msg.append(f"{tgt} - {compiler_config(tgt)}\n")
                for dep in mismatched_compiler_configs[tgt]:
                    msg.append(f"    {dep} - {compiler_config(dep)}\n")
            raise TaskError("".join(msg))

    def _must_have_sources(self, target):
        if isinstance(target, JavaThriftLibrary) and not target.payload.sources.source_paths:
            raise TargetDefinitionException(target, "no thrift files found")

    def synthetic_target_type(self, target):
        language = self._thrift_defaults.language(target)
        return self._target_type_for_language(language)

    def synthetic_target_extra_dependencies(self, target, target_workdir):
        deps = OrderedSet(self._thrift_dependencies_for_target(target))
        deps.update(target.dependencies)
        return deps

    def synthetic_target_extra_exports(self, target, target_workdir):
        dep_info = self._resolved_export_info
        target_declares_service = any(
            self._declares_service(source) for source in target.sources_relative_to_buildroot()
        )
        language = self._thrift_defaults.language(target)

        if target_declares_service:
            return dep_info.service[language]
        else:
            return dep_info.structs[language]

    def _thrift_dependencies_for_target(self, target):
        dep_info = self._resolved_dep_info
        target_declares_service_or_exception = any(
            self._declares_service(source) or self._declares_exception(source)
            for source in target.sources_relative_to_buildroot()
        )
        language = self._thrift_defaults.language(target)

        if target_declares_service_or_exception:
            return dep_info.service[language]
        else:
            return dep_info.structs[language]

    @memoized_property
    def _resolved_dep_info(self):
        return ScroogeGen.DepInfo(
            self._resolve_deps(self.get_options().service_deps),
            self._resolve_deps(self.get_options().structs_deps),
        )

    @memoized_property
    def _resolved_export_info(self):
        return ScroogeGen.DepInfo(
            self._resolve_deps(self.get_options().service_exports),
            self._resolve_deps(self.get_options().structs_exports),
        )

    @property
    def _copy_target_attributes(self):
        return super()._copy_target_attributes + ["strict_deps"]
