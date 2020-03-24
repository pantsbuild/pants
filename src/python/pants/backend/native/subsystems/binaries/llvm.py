# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker
from pants.backend.native.subsystems.utils.archive_file_mapper import ArchiveFileMapper
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.platform import Platform
from pants.engine.rules import RootRule, rule
from pants.util.dirutil import is_readable_dir
from pants.util.enums import match
from pants.util.memo import memoized_method, memoized_property


class LLVMReleaseUrlGenerator(BinaryToolUrlGenerator):

    _DIST_URL_FMT = "https://releases.llvm.org/{version}/{base}.tar.xz"

    _ARCHIVE_BASE_FMT = "clang+llvm-{version}-x86_64-{system_id}"

    # TODO: Give a more useful error message than KeyError if the host platform was not recognized
    # (and make it easy for other BinaryTool subclasses to do this as well).
    _SYSTEM_ID = {
        "mac": "apple-darwin",
        "linux": "linux-gnu-ubuntu-16.04",
    }

    def generate_urls(self, version, host_platform):
        system_id = self._SYSTEM_ID[host_platform.os_name]
        archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
        return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class LLVM(NativeTool):
    """Subsystem wrapping an archive providing an LLVM distribution.

    This subsystem provides the clang and clang++ compilers. It also provides lld, which is not
    currently used.

    NB: The lib and include dirs provided by this distribution are produced by using known relative
    paths into the distribution of LLVM from LLVMReleaseUrlGenerator. If LLVM changes the structure of
    their release archives, these methods may have to change. They should be stable to version
    upgrades, however.
    """

    options_scope = "llvm"
    default_version = "6.0.0"
    archive_type = "txz"

    def get_external_url_generator(self):
        return LLVMReleaseUrlGenerator()

    @memoized_method
    def select(self):
        unpacked_path = super().select()
        # The archive from releases.llvm.org wraps the extracted content into a directory one level
        # deeper, but the one from our S3 does not. We account for both here.
        children = os.listdir(unpacked_path)
        if len(children) == 1:
            llvm_base_dir = os.path.join(unpacked_path, children[0])
            assert is_readable_dir(llvm_base_dir)
            return llvm_base_dir
        return unpacked_path

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ArchiveFileMapper.scoped(cls),)

    @memoized_property
    def _file_mapper(self):
        return ArchiveFileMapper.scoped_instance(self)

    def _filemap(self, all_components_list):
        return self._file_mapper.map_files(self.select(), all_components_list)

    @memoized_property
    def path_entries(self):
        return self._filemap([("bin",)])

    # TODO(#5663): this is currently dead code.
    def linker(self, platform: Platform) -> Linker:
        return Linker(
            path_entries=self.path_entries,
            exe_filename=match(platform, {Platform.darwin: "ld64.lld", Platform.linux: "lld"}),
            runtime_library_dirs=(),
            linking_library_dirs=(),
            extra_args=(),
            extra_object_files=(),
        )

    @memoized_property
    def _common_include_dirs(self):
        return self._filemap([("lib/clang", self.version(), "include")])

    @memoized_property
    def _common_lib_dirs(self):
        return self._filemap([("lib",)])

    def c_compiler(self) -> CCompiler:
        return CCompiler(
            path_entries=self.path_entries,
            exe_filename="clang",
            runtime_library_dirs=self._common_lib_dirs,
            include_dirs=self._common_include_dirs,
            extra_args=(),
        )

    @memoized_property
    def _cpp_include_dirs(self):
        return self._filemap([("include/c++/v1",)])

    def cpp_compiler(self) -> CppCompiler:
        return CppCompiler(
            path_entries=self.path_entries,
            exe_filename="clang++",
            runtime_library_dirs=self._common_lib_dirs,
            include_dirs=(self._cpp_include_dirs + self._common_include_dirs),
            extra_args=(),
        )


# TODO(#5663): use this over the XCode linker!
@rule
def get_lld(platform: Platform, llvm: LLVM) -> Linker:
    return llvm.linker(platform)


@rule
def get_clang(llvm: LLVM) -> CCompiler:
    return llvm.c_compiler()


@rule
def get_clang_plusplus(llvm: LLVM) -> CppCompiler:
    return llvm.cpp_compiler()


def create_llvm_rules():
    return [
        get_lld,
        get_clang,
        get_clang_plusplus,
        RootRule(LLVM),
    ]
