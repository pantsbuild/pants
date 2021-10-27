# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os.path
from dataclasses import dataclass

import ijson

from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    AddPrefix,
    Digest,
    DigestSubset,
    GlobMatchErrorBehavior,
    PathGlobs,
    RemovePrefix,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.strutil import strip_prefix, strip_v2_chroot_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThirdPartyPkgInfo:
    """All the info and files needed to build a third-party package.

    The digest only contains the files for the package, with all prefixes stripped.
    """

    import_path: str
    subpath: str

    digest: Digest

    # Note that we don't care about test-related metadata like `TestImports`, as we'll never run
    # tests directly on a third-party package.
    imports: tuple[str, ...]
    go_files: tuple[str, ...]
    s_files: tuple[str, ...]

    unsupported_sources_error: NotImplementedError | None = None


@dataclass(frozen=True)
class ThirdPartyPkgInfoRequest(EngineAwareParameter):
    """Request the info and digest needed to build a third-party package.

    The package's module must be included in the input `go.mod`/`go.sum`.
    """

    import_path: str
    go_mod_stripped_digest: Digest

    def debug_hint(self) -> str:
        return self.import_path


@dataclass(frozen=True)
class AllThirdPartyPackages(FrozenDict[str, ThirdPartyPkgInfo]):
    digest: Digest
    import_paths_to_pkg_info: FrozenDict[str, ThirdPartyPkgInfo]


@dataclass(frozen=True)
class AllThirdPartyPackagesRequest:
    go_mod_stripped_digest: Digest


@rule
async def download_and_analyze_third_party_packages(
    request: AllThirdPartyPackagesRequest,
) -> AllThirdPartyPackages:
    # NB: We download all modules to GOPATH=$(pwd)/gopath. Running `go list ...` from $(pwd) would
    # naively try analyzing the contents of the GOPATH like they were first-party packages. This
    # results in errors like this:
    #
    #   package <import_path>/gopath/pkg/mod/golang.org/x/text@v0.3.0/unicode: can only use
    #   path@version syntax with 'go get' and 'go install' in module-aware mode
    #
    # Instead, we run `go list` from a subdirectory of the chroot. It can still access the
    # contents of `GOPATH`, but won't incorrectly treat its contents as first-party packages.
    go_mod_prefix = "go_mod_prefix"
    go_mod_prefixed_digest = await Get(
        Digest, AddPrefix(request.go_mod_stripped_digest, go_mod_prefix)
    )

    list_argv = (
        "list",
        # This rule can't modify `go.mod` and `go.sum` as it would require mutating the workspace.
        # Instead, we expect them to be well-formed already.
        #
        # It would be convenient to set `-mod=mod` to allow edits, and then compare the resulting
        # files to the input so that we could print a diff for the user to know how to update. But
        # `-mod=mod` results in more packages being downloaded and added to `go.mod` than is
        # actually necessary.
        # TODO: nice error when `go.mod` and `go.sum` would need to change. Right now, it's a
        #  message from Go and won't be intuitive for Pants users what to do.
        "-mod=readonly",
        # There may be some packages in the transitive closure that cannot be built, but we should
        # not blow up Pants.
        #
        # For example, a package that sets the special value `package documentation` and has no
        # source files would naively error due to `build constraints exclude all Go files`, even
        # though we should not error on that package.
        "-e",
        "-json",
        # This matches all packages. `all` only matches first-party packages and complains that
        # there are no `.go` files.
        "...",
    )
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=list_argv,
            # TODO: make this more descriptive: point to the actual `go_mod` target or path.
            description="Download and analyze all third-party Go packages",
            input_digest=go_mod_prefixed_digest,
            output_directories=("gopath/pkg/mod",),
            working_dir=go_mod_prefix,
            allow_downloads=True,
        ),
    )
    stripped_result_digest = await Get(
        Digest, RemovePrefix(list_result.output_digest, "gopath/pkg/mod")
    )

    all_digest_subset_gets = []
    all_pkg_info_kwargs = []
    for pkg_json in ijson.items(list_result.stdout, "", multiple_values=True):
        if "Standard" in pkg_json:
            continue
        import_path = pkg_json["ImportPath"]
        if import_path == "...":
            if "Error" not in pkg_json:
                raise AssertionError(
                    "`go list` included the import path `...`, but there was no `Error` attached. "
                    "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
                    f"with this error message:\n\n{pkg_json}"
                )
            # TODO: Improve this error message, such as better instructions if `go.sum` is stale.
            raise Exception(pkg_json["Error"]["Err"])

        if "Error" in pkg_json:
            err = pkg_json["Error"]["Err"]
            if "build constraints exclude all Go files" in err:
                logger.debug(
                    f"Skipping the Go third-party package `{import_path}` because of this "
                    f"error: {err}"
                )
                continue

            raise AssertionError(
                f"`go list` failed for the import path `{import_path}`. Please open an issue at "
                f"https://github.com/pantsbuild/pants/issues/new/choose so that we can figure out "
                f"how to support this:\n\n{err}"
            )

        dir_path = strip_prefix(strip_v2_chroot_path(pkg_json["Dir"]), "gopath/pkg/mod/")
        all_pkg_info_kwargs.append(
            dict(
                import_path=import_path,
                subpath=dir_path,
                imports=tuple(pkg_json.get("Imports", ())),
                go_files=tuple(pkg_json.get("GoFiles", ())),
                s_files=tuple(pkg_json.get("SFiles", ())),
                unsupported_sources_error=maybe_create_error_for_invalid_sources(
                    pkg_json, import_path
                ),
            )
        )
        all_digest_subset_gets.append(
            Get(
                Digest,
                DigestSubset(
                    stripped_result_digest,
                    PathGlobs(
                        [os.path.join(dir_path, "*")],
                        glob_match_error_behavior=GlobMatchErrorBehavior.error,
                        description_of_origin=f"downloading {import_path}",
                    ),
                ),
            )
        )

    all_digest_subsets = await MultiGet(all_digest_subset_gets)
    import_path_to_info = {
        pkg_info_kwargs["import_path"]: ThirdPartyPkgInfo(digest=digest_subset, **pkg_info_kwargs)
        for pkg_info_kwargs, digest_subset in zip(all_pkg_info_kwargs, all_digest_subsets)
    }
    return AllThirdPartyPackages(list_result.output_digest, FrozenDict(import_path_to_info))


@rule
async def extract_package_info(request: ThirdPartyPkgInfoRequest) -> ThirdPartyPkgInfo:
    all_packages = await Get(
        AllThirdPartyPackages, AllThirdPartyPackagesRequest(request.go_mod_stripped_digest)
    )
    pkg_info = all_packages.import_paths_to_pkg_info.get(request.import_path)
    if pkg_info is None:
        raise AssertionError(
            f"The package `{request.import_path}` was not downloaded, but Pants tried using it. "
            "This should not happen. Please open an issue at "
            "https://github.com/pantsbuild/pants/issues/new/choose with this error message."
        )

    # We error if trying to _use_ a package with unsupported sources (vs. only generating the
    # target definition).
    if pkg_info.unsupported_sources_error:
        raise pkg_info.unsupported_sources_error

    return pkg_info


def maybe_create_error_for_invalid_sources(
    go_list_json: dict, import_path: str
) -> NotImplementedError | None:
    for key in (
        "CgoFiles",
        "CompiledGoFiles",
        "CFiles",
        "CXXFiles",
        "MFiles",
        "HFiles",
        "FFiles",
        "SwigFiles",
        "SwigCXXFiles",
        "SysoFiles",
    ):
        if key in go_list_json:
            return NotImplementedError(
                f"The third-party package {import_path} includes `{key}`, which Pants does "
                "not yet support. Please open a feature request at "
                "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
                "prioritize adding support. Please include this error message and the version of "
                "the third-party module."
            )
    return None


def rules():
    return collect_rules()
