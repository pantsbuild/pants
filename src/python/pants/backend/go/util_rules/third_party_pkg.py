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
    EMPTY_DIGEST,
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
from pants.util.logging import LogLevel
from pants.util.strutil import strip_prefix, strip_v2_chroot_path

logger = logging.getLogger(__name__)


class GoThirdPartyPkgError(Exception):
    pass


@dataclass(frozen=True)
class ThirdPartyPkgInfo:
    """All the info and files needed to build a third-party package.

    The digest only contains the files for the package, with all prefixes stripped.
    """

    import_path: str

    digest: Digest
    dir_path: str

    # Note that we don't care about test-related metadata like `TestImports`, as we'll never run
    # tests directly on a third-party package.
    imports: tuple[str, ...]
    go_files: tuple[str, ...]
    s_files: tuple[str, ...]

    minimum_go_version: str | None

    error: GoThirdPartyPkgError | None = None


@dataclass(frozen=True)
class ThirdPartyPkgInfoRequest(EngineAwareParameter):
    """Request the info and digest needed to build a third-party package.

    The package's module must be included in the input `go.mod`/`go.sum`.
    """

    import_path: str
    go_mod_digest: Digest
    go_mod_path: str

    def debug_hint(self) -> str:
        return f"{self.import_path} from {self.go_mod_path}"


@dataclass(frozen=True)
class AllThirdPartyPackages(FrozenDict[str, ThirdPartyPkgInfo]):
    """All the packages downloaded from a go.mod, along with a digest of the downloaded files.

    The digest has files in the format `gopath/pkg/mod`, which is what `GoSdkProcess` sets `GOPATH`
    to. This means that you can include the digest in a process and Go will properly consume it as
    the `GOPATH`.
    """

    digest: Digest
    import_paths_to_pkg_info: FrozenDict[str, ThirdPartyPkgInfo]


@dataclass(frozen=True)
class AllThirdPartyPackagesRequest:
    go_mod_digest: Digest
    go_mod_path: str


@rule(desc="Download and analyze all third-party Go packages", level=LogLevel.DEBUG)
async def download_and_analyze_third_party_packages(
    request: AllThirdPartyPackagesRequest,
) -> AllThirdPartyPackages:
    # NB: We download all modules to GOPATH={chroot}/gopath. Running `go list ...` from {chroot}
    # would naively try analyzing the contents of the GOPATH like they were first-party packages.
    # This results in errors like this:
    #
    #   package <import_path>/gopath/pkg/mod/golang.org/x/text@v0.3.0/unicode: can only use
    #   path@version syntax with 'go get' and 'go install' in module-aware mode
    #
    # Instead, we make sure we run `go list` from a subdirectory of the chroot. It can still
    # access the contents of `GOPATH`, but won't incorrectly treat its contents as
    # first-party packages.
    go_mod_dir = os.path.dirname(request.go_mod_path)
    if not go_mod_dir:
        go_mod_dir = "go_mod_prefix"
        go_mod_digest = await Get(Digest, AddPrefix(request.go_mod_digest, go_mod_dir))
    else:
        go_mod_digest = request.go_mod_digest

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
            description=f"Run `go list` to download {request.go_mod_path}",
            input_digest=go_mod_digest,
            output_directories=("gopath/pkg/mod",),
            working_dir=go_mod_dir,
            allow_downloads=True,
        ),
    )
    stripped_result_digest = await Get(
        Digest, RemovePrefix(list_result.output_digest, "gopath/pkg/mod")
    )

    all_digest_subset_gets = []
    all_pkg_info_kwargs = []
    all_failed_pkg_info = []
    for pkg_json in ijson.items(list_result.stdout, "", multiple_values=True):
        if "Standard" in pkg_json:
            continue
        import_path = pkg_json["ImportPath"]

        maybe_error, maybe_failed_pkg_info = maybe_raise_or_create_error_or_create_failed_pkg_info(
            pkg_json, import_path
        )
        if maybe_failed_pkg_info:
            all_failed_pkg_info.append(maybe_failed_pkg_info)
            continue

        dir_path = strip_prefix(strip_v2_chroot_path(pkg_json["Dir"]), "gopath/pkg/mod/")
        all_pkg_info_kwargs.append(
            dict(
                import_path=import_path,
                dir_path=dir_path,
                imports=tuple(pkg_json.get("Imports", ())),
                go_files=tuple(pkg_json.get("GoFiles", ())),
                s_files=tuple(pkg_json.get("SFiles", ())),
                minimum_go_version=pkg_json.get("Module", {}).get("GoVersion"),
                error=maybe_error,
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
    import_path_to_info.update((pkg_info.import_path, pkg_info) for pkg_info in all_failed_pkg_info)
    return AllThirdPartyPackages(list_result.output_digest, FrozenDict(import_path_to_info))


@rule
async def extract_package_info(request: ThirdPartyPkgInfoRequest) -> ThirdPartyPkgInfo:
    all_packages = await Get(
        AllThirdPartyPackages,
        AllThirdPartyPackagesRequest(request.go_mod_digest, request.go_mod_path),
    )
    pkg_info = all_packages.import_paths_to_pkg_info.get(request.import_path)
    if pkg_info:
        return pkg_info
    raise AssertionError(
        f"The package `{request.import_path}` was not downloaded, but Pants tried using it. "
        "This should not happen. Please open an issue at "
        "https://github.com/pantsbuild/pants/issues/new/choose with this error message."
    )


def maybe_raise_or_create_error_or_create_failed_pkg_info(
    go_list_json: dict, import_path: str
) -> tuple[GoThirdPartyPkgError | None, ThirdPartyPkgInfo | None]:
    """Error for unrecoverable errors, otherwise lazily create an error or `ThirdPartyPkgInfo` for
    recoverable errors.

    Lazy errors should only be raised when the package is compiled, but not during target generation
    and project introspection. This is important so that we don't overzealously error on packages
    that the user doesn't actually ever use, given how a Go module includes all of its packages,
    even test packages that are never used by first-party code.

    Returns a `ThirdPartyPkgInfo` if the `Dir` key is missing, which is necessary for our normal
    analysis of the package.
    """
    if import_path == "...":
        if "Error" not in go_list_json:
            raise AssertionError(
                "`go list` included the import path `...`, but there was no `Error` attached. "
                "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
                f"with this error message:\n\n{go_list_json}"
            )
        # TODO: Improve this error message, such as better instructions if `go.sum` is stale.
        raise GoThirdPartyPkgError(go_list_json["Error"]["Err"])

    if "Dir" not in go_list_json:
        error = GoThirdPartyPkgError(
            f"`go list` failed for the import path `{import_path}` because `Dir` was not defined. "
            f"Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose so "
            f"that we can figure out how to support this:"
            f"\n\n{go_list_json}"
        )
        return None, ThirdPartyPkgInfo(
            import_path=import_path,
            dir_path="",
            digest=EMPTY_DIGEST,
            imports=(),
            go_files=(),
            s_files=(),
            minimum_go_version=None,
            error=error,
        )

    if "Error" in go_list_json:
        err_msg = go_list_json["Error"]["Err"]
        return (
            GoThirdPartyPkgError(
                f"`go list` failed for the import path `{import_path}`. Please open an issue at "
                "https://github.com/pantsbuild/pants/issues/new/choose so that we can figure out "
                "how to support this:"
                f"\n\n{err_msg}\n\n{go_list_json}"
            ),
            None,
        )

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
            return (
                GoThirdPartyPkgError(
                    f"The third-party package {import_path} includes `{key}`, which Pants does "
                    "not yet support. Please open a feature request at "
                    "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
                    "prioritize adding support. Please include this error message and the version of "
                    "the third-party module."
                ),
                None,
            )
    return None, None


def rules():
    return collect_rules()
