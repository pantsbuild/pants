# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import json
import logging
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidPythonLockfileReason,
    LockfileFormat,
    PythonLockfileMetadata,
    PythonLockfileMetadataV2,
    PythonLockfileMetadataV8,
)
from pants.build_graph.address import Address
from pants.core.util_rules.lockfile_metadata import (
    InvalidLockfileError,
    LockfileMetadataValidation,
    NoLockfileMetadataBlock,
)
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, FileContent, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.native_engine import IntrinsicError
from pants.engine.intrinsics import (
    create_digest,
    get_digest_contents,
    get_digest_entries,
    path_globs_to_digest,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionMembership
from pants.util.docutil import bin_name, doc_url
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.pip_requirement import PipRequirement
from pants.util.requirements import parse_requirements_file
from pants.util.strutil import comma_separated_list, pluralize, softwrap

if TYPE_CHECKING:
    from pants.backend.python.util_rules.pex import Pex


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolve:
    # A named resolve for a "user lockfile".
    # Soon to be the only kind of lockfile, as this class will help
    # get rid of the "tool lockfile" concept.
    # TODO: Once we get rid of old-style tool lockfiles we can possibly
    #  unify this with EntireLockfile.
    # TODO: We might want to add the requirements subset to this data structure,
    #  to further detangle this from PexRequirements.
    name: str

    use_entire_lockfile: bool


@dataclass(frozen=True)
class Lockfile:
    url: str
    url_description_of_origin: str
    resolve_name: str
    lockfile_hex_digest: str | None = None


@rule
async def get_lockfile_for_resolve(resolve: Resolve, python_setup: PythonSetup) -> Lockfile:
    lockfile_path = python_setup.resolves.get(resolve.name)
    if not lockfile_path:
        raise ValueError(f"No such resolve: {resolve.name}")
    return Lockfile(
        url=lockfile_path,
        url_description_of_origin=f"the resolve `{resolve.name}`",
        resolve_name=resolve.name,
    )


@dataclass(frozen=True)
class LoadedLockfile:
    """A lockfile after loading and header stripping.

    Validation is deferred until consumption time, because each consumed subset (in the case of a
    PEX-native lockfile) can be individually validated.
    """

    # The digest of the loaded lockfile (which may not be identical to the input).
    lockfile_digest: Digest
    # The path of the loaded lockfile within the Digest.
    lockfile_path: str
    # The loaded metadata for this lockfile, if any.
    metadata: PythonLockfileMetadata | None = field(hash=False)
    # An estimate of the number of requirements in this lockfile, to be used as a heuristic for
    # available parallelism.
    requirement_estimate: int
    # The format of the loaded lockfile.
    lockfile_format: LockfileFormat
    # If lockfile_format is ConstraintsDeprecated, the lockfile parsed as constraints strings,
    # for use when the lockfile needs to be subsetted (see #15031, ##12222).
    as_constraints_strings: FrozenOrderedSet[str] | None
    # The original file or file content (which may not have identical content to the output
    # `lockfile_digest`).
    original_lockfile: Lockfile


@dataclass(frozen=True)
class LoadedLockfileRequest:
    """A request to load and validate the content of the given lockfile."""

    lockfile: Lockfile


def strip_comments_from_pex_json_lockfile(lockfile_bytes: bytes) -> bytes:
    """Pex does not like the header Pants adds to lockfiles, as it violates JSON.

    Note that we only strip lines starting with `//`, which is all that Pants will ever add. If
    users add their own comments, things will fail.
    """
    return b"\n".join(
        line for line in lockfile_bytes.splitlines() if not line.lstrip().startswith(b"//")
    )


def is_probably_pex_json_lockfile(lockfile_bytes: bytes) -> bool:
    for line in lockfile_bytes.splitlines():
        if line and not line.startswith(b"//"):
            # Note that pip/Pex complain if a requirements.txt style starts with `{`.
            return line.lstrip().startswith(b"{")
    return False


def _pex_lockfile_requirement_count(lockfile_bytes: bytes) -> int:
    # TODO: this is a very naive heuristic that will overcount, and also relies on Pants
    #  setting `--indent` when generating lockfiles. More robust would be parsing the JSON
    #  and getting the len(locked_resolves.locked_requirements.project_name), but we risk
    #  if Pex ever changes its lockfile format.

    num_lines = len(lockfile_bytes.splitlines())
    # These are very naive estimates, and they bias towards overcounting. For example, requirements
    # often are 20+ lines.
    num_lines_for_options = 10
    lines_per_req = 10
    return max((num_lines - num_lines_for_options) // lines_per_req, 2)


def get_metadata(
    python_setup: PythonSetup,
    lock_bytes: bytes,
    lockfile_path: str | None,
    resolve_name: str,
    delimiter: str,
) -> PythonLockfileMetadata | None:
    metadata: PythonLockfileMetadata | None = None
    if python_setup.invalid_lockfile_behavior != InvalidLockfileBehavior.ignore:
        try:
            metadata = PythonLockfileMetadata.from_lockfile(
                lockfile=lock_bytes,
                lockfile_path=lockfile_path,
                resolve_name=resolve_name,
                delimeter=delimiter,
            )
        except NoLockfileMetadataBlock:
            # We don't validate if the file isn't a pants-generated lockfile (as determined
            # by the lack of a metadata block). But we propagate any other type of
            # InvalidLockfileError incurred while parsing the metadata block.
            logger.debug(
                f"Lockfile for resolve {resolve_name} "
                f"{('at ' + lockfile_path) if lockfile_path else ''}"
                f" has no metadata block, so was not generated by Pants. "
                f"Lockfile will not be validated."
            )
    return metadata


async def read_file_or_resource(url: str, description_of_origin: str) -> Digest:
    """Read from a path, file:// or resource:// URL and return the digest of the content.

    If no content is found at the path/URL, raise.
    """
    parts = urlparse(url)
    # urlparse retains the leading / in URLs with a netloc.
    path = parts.path[1:] if parts.path.startswith("/") else parts.path
    if parts.scheme in {"", "file"}:
        digest = await path_globs_to_digest(
            PathGlobs(
                [path],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=description_of_origin,
            )
        )
    elif parts.scheme == "resource":
        _fc = FileContent(
            path,
            # The "netloc" in our made-up "resource://" scheme is the package.
            importlib.resources.files(parts.netloc).joinpath(path).read_bytes(),
        )
        digest = await create_digest(CreateDigest([_fc]))
    else:
        raise ValueError(
            f"Unsupported scheme {parts.scheme} for URL: {url} (origin: {description_of_origin})"
        )
    return digest


@rule
async def load_lockfile(
    request: LoadedLockfileRequest,
    python_setup: PythonSetup,
) -> LoadedLockfile:
    lockfile = request.lockfile
    # TODO: This is temporary. Once we regenerate all embedded lockfiles to have sidecar metadata
    #  files instead of metadata front matter, we won't need to call get_metadata() on them.
    synthetic_lock = lockfile.url.startswith("resource://")
    lockfile_digest = await read_file_or_resource(lockfile.url, lockfile.url_description_of_origin)
    lockfile_digest_entries = await get_digest_entries(lockfile_digest)
    lockfile_path = lockfile_digest_entries[0].path

    lockfile_contents = await get_digest_contents(lockfile_digest)
    lock_bytes = lockfile_contents[0].content
    lockfile_format: LockfileFormat | None = None
    constraints_strings = None

    metadata_url = PythonLockfileMetadata.metadata_location_for_lockfile(lockfile.url)
    metadata = None

    # If there's a sidecar metadata file, always load it, at least to get the lockfile_format.
    try:
        metadata_digest = await read_file_or_resource(
            metadata_url,
            description_of_origin="We squelch errors, so this is never seen by users",
        )
        digest_contents = await get_digest_contents(metadata_digest)
        metadata_bytes = digest_contents[0].content
        json_dict = json.loads(metadata_bytes)
        metadata = PythonLockfileMetadata.from_json_dict(
            json_dict,
            lockfile_description=f"the lockfile for `{lockfile.resolve_name}`",
            error_suffix=softwrap(
                f"""
                To resolve this error, you will need to regenerate the lockfile by running
                `{bin_name()} generate-lockfiles --resolve={lockfile.resolve_name}.
                """
            ),
        )
        if isinstance(metadata, PythonLockfileMetadataV8):
            lockfile_format = metadata.lockfile_format
    except IntrinsicError:
        # No metadata file or resource found, so fall through to finding a metadata header block
        # prepended to the lockfile itself.
        pass

    # If this is a uv lockfile then its metadata will have told us so, otherwise fall back
    # to detection (since older lockfiles may not have the format field in the metadata).
    lockfile_format = lockfile_format or (
        LockfileFormat.PEX
        if is_probably_pex_json_lockfile(lock_bytes)
        else LockfileFormat.CONSTRAINTS_DEPRECATED
    )

    if lockfile_format == LockfileFormat.CONSTRAINTS_DEPRECATED:
        lock_string = lock_bytes.decode()
        constraints_strings = FrozenOrderedSet(
            str(req) for req in parse_requirements_file(lock_string, rel_path=lockfile_path)
        )

    if lockfile_format == LockfileFormat.PEX:
        stripped_lock_bytes = strip_comments_from_pex_json_lockfile(lock_bytes)
        lockfile_digest = await create_digest(
            CreateDigest([FileContent(lockfile_path, stripped_lock_bytes)])
        )

    if not metadata and python_setup.invalid_lockfile_behavior != InvalidLockfileBehavior.ignore:
        # uv lockfiles must have sidecar metadata, so this can only be Pex or ConstraintsDeprecated.
        header_delimiter = "//" if lockfile_format == LockfileFormat.PEX else "#"
        metadata = get_metadata(
            python_setup,
            lock_bytes,
            None if synthetic_lock else lockfile_path,
            lockfile.resolve_name,
            header_delimiter,
        )

    match lockfile_format:
        case LockfileFormat.UV:
            # Use the virtual root package's direct dependencies as a rough estimate
            # of how many packages need resolving.
            # NB: The uv project recommends not relying on lockfile internals, but
            # this particular aspect seems relatively stable in practice.
            lockfile_toml = tomllib.loads(lock_bytes.decode())
            root_package = next(
                (
                    p
                    for p in lockfile_toml.get("package", [])
                    if p.get("source", {}).get("virtual") == "."
                ),
                None,
            )
            deps = root_package.get("dependencies") if root_package else None
            if deps is None:
                logger.warning(
                    f"Couldn't find the virtual root [[package]].dependencies entry in {lockfile_path}. "
                    "Has the uv lockfile format changed? This will not affect correctness but "
                    "may affect performance. Please reach out to the Pants team if you encounter "
                    "this warning."
                )
            requirement_estimate = 4 if deps is None else len(deps)
        case LockfileFormat.PEX:
            requirement_estimate = _pex_lockfile_requirement_count(lock_bytes)
        case LockfileFormat.CONSTRAINTS_DEPRECATED:
            # Note: this is a very naive heuristic. It will overcount because entries often
            # have >1 line due to `--hash`.
            requirement_estimate = len(lock_bytes.splitlines())
        case _:
            raise ValueError(f"Unknown lockfile format: {lockfile_format}")

    return LoadedLockfile(
        lockfile_digest,
        lockfile_path,
        metadata,
        requirement_estimate,
        lockfile_format,
        constraints_strings,
        original_lockfile=lockfile,
    )


@dataclass(frozen=True)
class EntireLockfile:
    """A request to resolve the entire contents of a lockfile.

    This resolution mode is used in a few cases:
    1. for poetry or handwritten lockfiles (which do not support being natively subsetted the
       way that a PEX lockfile can be), in order to build a repository-PEX to subset separately.
    2. for tool lockfiles, which (regardless of format), need to resolve the entire lockfile
       content anyway.
    """

    lockfile: Lockfile
    # If available, the current complete set of requirement strings that influence this lockfile.
    # Used for metadata validation.
    complete_req_strings: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PexRequirements:
    """A request to resolve a series of requirements (optionally from a "superset" resolve)."""

    req_strings_or_addrs: FrozenOrderedSet[str | Address]
    constraints_strings: FrozenOrderedSet[str]
    # If these requirements should be resolved as a subset of either a repository PEX, or a
    # PEX-native lockfile, the superset to use. # NB: Use of a lockfile here asserts that the
    # lockfile is PEX-native, because legacy lockfiles do not support subset resolves.
    from_superset: Pex | Resolve | None
    description_of_origin: str

    def __init__(
        self,
        req_strings_or_addrs: Iterable[str | Address] = (),
        *,
        constraints_strings: Iterable[str] = (),
        from_superset: Pex | Resolve | None = None,
        description_of_origin: str = "",
    ) -> None:
        """
        :param req_strings_or_addrs: The requirement strings to resolve, or addresses
          of targets that refer to them, or string specs of such addresses.
        :param constraints_strings: Constraints strings to apply during the resolve.
        :param from_superset: An optional superset PEX or lockfile to resolve the req strings from.
        :param description_of_origin: A human-readable description of what these requirements
          represent, for use in error messages.
        """
        object.__setattr__(
            self, "req_strings_or_addrs", FrozenOrderedSet(sorted(req_strings_or_addrs))
        )
        object.__setattr__(
            self, "constraints_strings", FrozenOrderedSet(sorted(constraints_strings))
        )
        object.__setattr__(self, "from_superset", from_superset)
        object.__setattr__(self, "description_of_origin", description_of_origin)

    @classmethod
    def req_strings_from_requirement_fields(
        cls, fields: Iterable[PythonRequirementsField]
    ) -> FrozenOrderedSet[str]:
        """A convenience when you only need the raw requirement strings from fields and don't need
        to consider things like constraints or resolves."""
        return FrozenOrderedSet(
            sorted(str(python_req) for fld in fields for python_req in fld.value)
        )

    def __bool__(self) -> bool:
        return bool(self.req_strings_or_addrs)


@dataclass(frozen=True)
class ResolvePexConstraintsFile:
    digest: Digest
    path: str
    constraints: FrozenOrderedSet[PipRequirement]


@dataclass(frozen=True)
class ResolveConfig:
    """Configuration from `[python]` that impacts how the resolve is created."""

    indexes: tuple[str, ...]
    find_links: tuple[str, ...]
    manylinux: str | None
    constraints_file: ResolvePexConstraintsFile | None
    only_binary: FrozenOrderedSet[str]
    no_binary: FrozenOrderedSet[str]
    excludes: FrozenOrderedSet[str]
    overrides: FrozenOrderedSet[str]
    sources: FrozenOrderedSet[str]
    path_mappings: tuple[str, ...]
    lock_style: str
    complete_platforms: tuple[str, ...]
    uploaded_prior_to: str | None

    def pex_args(self) -> Iterator[str]:
        """Arguments for Pex for indexes/--find-links, manylinux, and path mappings.

        Does not include arguments for constraints files, which must be set up independently.
        """
        # NB: In setting `--no-pypi`, we rely on the default value of `[python-repos].indexes`
        # including PyPI, which will override `--no-pypi` and result in using PyPI in the default
        # case. Why set `--no-pypi`, then? We need to do this so that
        # `[python-repos].indexes = ['custom_url']` will only point to that index and not include
        # PyPI.
        yield "--no-pypi"
        yield from (f"--index={index}" for index in self.indexes)
        yield from (f"--find-links={repo}" for repo in self.find_links)

        if self.manylinux:
            yield "--manylinux"
            yield self.manylinux
        else:
            yield "--no-manylinux"

        # Pex logically plumbs through equivalent settings, but uses a
        # separate flag instead of the Pip magic :all:/:none: syntax.  To
        # support the exitings Pants config settings we need to go from
        # :all:/:none: --> Pex options, which Pex will translate back into Pip
        # options.  Note that Pex's --wheel (for example) means "allow
        # wheels", not "require wheels".
        if self.only_binary and ":all:" in self.only_binary:
            yield "--wheel"
            yield "--no-build"
        elif self.only_binary and ":none:" in self.only_binary:
            yield "--no-wheel"
            yield "--build"
        elif self.only_binary:
            yield from (f"--only-binary={pkg}" for pkg in self.only_binary)

        if self.no_binary and ":all:" in self.no_binary:
            yield "--no-wheel"
            yield "--build"
        elif self.no_binary and ":none:" in self.no_binary:
            yield "--wheel"
            yield "--no-build"
        elif self.no_binary:
            yield from (f"--only-build={pkg}" for pkg in self.no_binary)

        yield from (f"--path-mapping={v}" for v in self.path_mappings)

        yield from (f"--exclude={exclude}" for exclude in self.excludes)
        yield from (f"--source={source}" for source in self.sources)

        if self.uploaded_prior_to:
            yield f"--uploaded-prior-to={self.uploaded_prior_to}"

    def uv_config(self, extra_find_links: Iterable[str] = ()) -> str:
        """Content for uv.toml based on this resolve's configuration.

        Only uv-supported fields are used. Call validate_for_uv() first to ensure no
        pex-specific fields are set.
        """
        config_lines: list[str] = []

        if not self.indexes:
            config_lines.append("no-index = true")

        all_find_links = (*self.find_links, *extra_find_links)
        if all_find_links:
            entries = "\n".join(f'    "{fl}",' for fl in all_find_links)
            config_lines.append(f"find-links = [\n{entries}\n]")

        if self.no_binary:
            if ":all:" in self.no_binary:
                config_lines.append("no-binary = true")
            elif ":none:" not in self.no_binary:
                entries = "\n".join(f'    "{pkg}",' for pkg in self.no_binary)
                config_lines.append(f"no-binary-package = [\n{entries}\n]")

        if self.only_binary:
            if ":all:" in self.only_binary:
                config_lines.append("no-build = true")
            elif ":none:" not in self.only_binary:
                entries = "\n".join(f'    "{pkg}",' for pkg in self.only_binary)
                config_lines.append(f"no-build-package = [\n{entries}\n]")

        if self.uploaded_prior_to:
            config_lines.append(f'exclude-newer = "{self.uploaded_prior_to}"')

        for i, index_url in enumerate(self.indexes):
            # The first index gets `default = true`, replacing uv's built-in PyPI default.
            # Subsequent indexes are additional sources.
            block = f'[[index]]\nurl = "{index_url}"\n'
            block += "default = true\n" if i == 0 else f'name = "extra-{i}"\n'
            config_lines.append(block)

        return "\n".join(config_lines) + "\n" if config_lines else ""

    def validate_for_uv(self, resolve_name: str) -> None:
        """Raise if any pex-specific resolve options are set that have no uv equivalent."""
        pex_specific: list[str] = []
        if self.constraints_file:
            pex_specific.append("`[python].resolves_to_constraints_file`")
        if self.complete_platforms:
            pex_specific.append("`[python].resolves_to_complete_platforms`")
        if self.excludes:
            pex_specific.append("`[python].resolves_to_excludes`")
        if self.overrides:
            pex_specific.append("`[python].resolves_to_overrides`")
        if self.sources:
            pex_specific.append("`[python].resolves_to_sources`")
        if self.lock_style != "universal":
            pex_specific.append("`[python]._resolves_to_lock_style`")
        if self.path_mappings:
            pex_specific.append("`[python-repos].path_mappings`")
        if pex_specific:
            raise ValueError(
                f"The following options are set for the resolve `{resolve_name}` but are not "
                f"supported when using the uv resolver:\n"
                + "\n".join(f"  - {opt}" for opt in pex_specific)
            )


@dataclass(frozen=True)
class ResolveConfigRequest(EngineAwareParameter):
    """Find all configuration from `[python]` that impacts how the resolve is created.

    If `resolve_name` is None, then most per-resolve options will be ignored because there is no way
    for users to configure them. However, some options like `[python-repos].indexes` will still be
    loaded.
    """

    resolve_name: str | None

    def debug_hint(self) -> str:
        return self.resolve_name or "<no resolve>"


@rule
async def determine_resolve_config(
    request: ResolveConfigRequest,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    union_membership: UnionMembership,
) -> ResolveConfig:
    if request.resolve_name is None:
        return ResolveConfig(
            indexes=python_repos.indexes,
            find_links=python_repos.find_links,
            manylinux=python_setup.manylinux,
            constraints_file=None,
            no_binary=FrozenOrderedSet(),
            only_binary=FrozenOrderedSet(),
            excludes=FrozenOrderedSet(),
            overrides=FrozenOrderedSet(),
            sources=FrozenOrderedSet(),
            path_mappings=python_repos.path_mappings,
            lock_style="universal",  # Default to universal when no resolve name
            complete_platforms=(),  # No complete platforms by default
            uploaded_prior_to=None,
        )

    no_binary = python_setup.resolves_to_no_binary().get(request.resolve_name) or []
    only_binary = python_setup.resolves_to_only_binary().get(request.resolve_name) or []
    excludes = python_setup.resolves_to_excludes().get(request.resolve_name) or []
    overrides = python_setup.resolves_to_overrides().get(request.resolve_name) or []
    sources = python_setup.resolves_to_sources().get(request.resolve_name) or []
    lock_style = python_setup.resolves_to_lock_style().get(request.resolve_name) or "universal"
    complete_platforms = tuple(
        python_setup.resolves_to_complete_platforms().get(request.resolve_name) or []
    )
    uploaded_prior_to = python_setup.resolves_to_uploaded_prior_to().get(request.resolve_name)

    constraints_file: ResolvePexConstraintsFile | None = None
    _constraints_file_path = python_setup.resolves_to_constraints_file().get(request.resolve_name)
    if _constraints_file_path:
        _constraints_origin = softwrap(
            f"""
            the option `[python].resolves_to_constraints_file` for the resolve
            '{request.resolve_name}'
            """
        )
        _constraints_path_globs = PathGlobs(
            [_constraints_file_path] if _constraints_file_path else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=_constraints_origin,
        )
        # TODO: Probably re-doing work here - instead of just calling one, then the next
        _constraints_digest, _constraints_digest_contents = await concurrently(
            path_globs_to_digest(_constraints_path_globs),
            get_digest_contents(**implicitly({_constraints_path_globs: PathGlobs})),
        )

        if len(_constraints_digest_contents) != 1:
            raise ValueError(
                softwrap(
                    f"""
                    Expected only one file from {_constraints_origin}, but matched:
                    {sorted(fc.path for fc in _constraints_digest_contents)}

                    Did you use a glob like `*`?
                    """
                )
            )
        _constraints_file_content = next(iter(_constraints_digest_contents))
        constraints = parse_requirements_file(
            _constraints_file_content.content.decode("utf-8"), rel_path=_constraints_file_path
        )
        constraints_file = ResolvePexConstraintsFile(
            _constraints_digest, _constraints_file_path, FrozenOrderedSet(constraints)
        )

    return ResolveConfig(
        indexes=python_repos.indexes,
        find_links=python_repos.find_links,
        manylinux=python_setup.manylinux,
        constraints_file=constraints_file,
        no_binary=FrozenOrderedSet(no_binary),
        only_binary=FrozenOrderedSet(only_binary),
        excludes=FrozenOrderedSet(excludes),
        overrides=FrozenOrderedSet(overrides),
        sources=FrozenOrderedSet(sources),
        path_mappings=python_repos.path_mappings,
        lock_style=lock_style,
        complete_platforms=complete_platforms,
        uploaded_prior_to=uploaded_prior_to,
    )


def validate_metadata(
    metadata: PythonLockfileMetadata,
    interpreter_constraints: InterpreterConstraints,
    lockfile: Lockfile,
    consumed_req_strings: Iterable[str],
    validate_consumed_req_strings: bool,
    python_setup: PythonSetup,
    resolve_config: ResolveConfig,
) -> None:
    """Given interpreter constraints and requirements to be consumed, validate lockfile metadata."""

    # TODO(#12314): Improve the exception if invalid strings
    user_requirements = [PipRequirement.parse(i) for i in consumed_req_strings]
    validation = metadata.is_valid_for(
        expected_invalidation_digest=lockfile.lockfile_hex_digest,
        user_interpreter_constraints=interpreter_constraints,
        interpreter_universe=python_setup.interpreter_versions_universe,
        user_requirements=user_requirements if validate_consumed_req_strings else {},
        manylinux=resolve_config.manylinux,
        requirement_constraints=(
            resolve_config.constraints_file.constraints
            if resolve_config.constraints_file
            else set()
        ),
        only_binary=resolve_config.only_binary,
        no_binary=resolve_config.no_binary,
        excludes=resolve_config.excludes,
        overrides=resolve_config.overrides,
        sources=resolve_config.sources,
        lock_style=resolve_config.lock_style,
        complete_platforms=resolve_config.complete_platforms,
        uploaded_prior_to=resolve_config.uploaded_prior_to,
    )
    if validation:
        return

    error_msg_kwargs = dict(
        metadata=metadata,
        validation=validation,
        lockfile=lockfile,
        is_default_user_lockfile=lockfile.resolve_name == python_setup.default_resolve,
        user_interpreter_constraints=interpreter_constraints,
        user_requirements=user_requirements,
        maybe_constraints_file_path=(
            resolve_config.constraints_file.path if resolve_config.constraints_file else None
        ),
    )
    msg_iter = _invalid_lockfile_error(**error_msg_kwargs)  # type: ignore[arg-type]
    msg = "".join(msg_iter).strip()
    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.error:
        raise InvalidLockfileError(msg)
    logger.warning(msg)


def _common_failure_reasons(
    failure_reasons: set[InvalidPythonLockfileReason], maybe_constraints_file_path: str | None
) -> Iterator[str]:
    if InvalidPythonLockfileReason.CONSTRAINTS_FILE_MISMATCH in failure_reasons:
        if maybe_constraints_file_path is None:
            yield softwrap(
                """
                - Constraint file expected from lockfile metadata but no
                constraints file configured.  See the option
                `[python].resolves_to_constraints_file`.
                """
            )
        else:
            yield softwrap(
                f"""
                - The constraints file at {maybe_constraints_file_path} has changed from when the
                lockfile was generated. (Constraints files are set via the option
                `[python].resolves_to_constraints_file`)
                """
            )
    if InvalidPythonLockfileReason.ONLY_BINARY_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `only_binary` arguments have changed from when the lockfile was generated.
            (`only_binary` is set via the options `[python].resolves_to_only_binary` and deprecated
            `[python].only_binary`)
            """
        )
    if InvalidPythonLockfileReason.NO_BINARY_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `no_binary` arguments have changed from when the lockfile was generated.
            (`no_binary` is set via the options `[python].resolves_to_no_binary` and deprecated
            `[python].no_binary`)
            """
        )
    if InvalidPythonLockfileReason.MANYLINUX_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `manylinux` argument has changed from when the lockfile was generated.
            (manylinux is set via the option `[python].resolver_manylinux`)
            """
        )
    if InvalidPythonLockfileReason.UPLOADED_PRIOR_TO_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `uploaded_prior_to` argument has changed from when the lockfile was generated.
            (uploaded_prior_to is set via the option `[python].resolves_to_uploaded_prior_to`)
            """
        )


def _invalid_lockfile_error(
    metadata: PythonLockfileMetadata,
    validation: LockfileMetadataValidation,
    lockfile: Lockfile,
    *,
    is_default_user_lockfile: bool,
    user_requirements: list[PipRequirement],
    user_interpreter_constraints: InterpreterConstraints,
    maybe_constraints_file_path: str | None,
) -> Iterator[str]:
    resolve = lockfile.resolve_name
    consumed_msg_parts = [f"`{str(r)}`" for r in user_requirements[0:2]]
    if len(user_requirements) > 2:
        consumed_msg_parts.append(
            f"{len(user_requirements) - 2} other "
            f"{pluralize(len(user_requirements) - 2, 'requirement', include_count=False)}"
        )

    yield f"\n\nYou are consuming {comma_separated_list(consumed_msg_parts)} from "
    if lockfile.url.startswith("resource://"):
        yield f"the built-in `{resolve}` lockfile provided by Pants "
    else:
        yield f"the `{resolve}` lockfile at {lockfile.url} "
    yield "with incompatible inputs.\n\n"

    if any(
        i
        in (
            InvalidPythonLockfileReason.INVALIDATION_DIGEST_MISMATCH,
            InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH,
        )
        for i in validation.failure_reasons
    ):
        yield (
            softwrap(
                """
            - The lockfile does not provide all the necessary requirements. You must
            modify the input requirements and/or regenerate the lockfile (see below).
            """
            )
            + "\n\n"
        )
        if is_default_user_lockfile:
            yield softwrap(
                f"""
                - The necessary requirements are specified by requirements targets marked with
                `resolve="{resolve}"`, or those with no explicit resolve (since `{resolve}` is the
                default for this repo).

                - The lockfile destination is specified by the `{resolve}` key in `[python].resolves`.
                """
            )
        else:
            yield softwrap(
                f"""
                - The necessary requirements are specified by requirements targets marked with
                `resolve="{resolve}"`.

                - The lockfile destination is specified by the `{resolve}` key in
                `[python].resolves`.
                """
            )

        if isinstance(metadata, PythonLockfileMetadataV2):
            # Note that by the time we have gotten to this error message, we should have already
            # validated that the transitive closure is using the same resolve, via
            # pex_from_targets.py. This implies that we don't need to worry about users depending
            # on python_requirement targets that aren't in that code's resolve.
            not_in_lock = sorted(str(r) for r in set(user_requirements) - metadata.requirements)
            yield f"\n\n- The requirements not provided by the `{resolve}` resolve are:\n  "
            yield str(not_in_lock)

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield "\n\n"
        yield softwrap(
            f"""
            - The inputs use interpreter constraints (`{user_interpreter_constraints}`) that
            are not a subset of those used to generate the lockfile
            (`{metadata.valid_for_interpreter_constraints}`).

            - The input interpreter constraints are specified by your code, using
            the `[python].interpreter_constraints` option and the `interpreter_constraints`
            target field.

            - To create a lockfile with new interpreter constraints, update the option
            `[python].resolves_to_interpreter_constraints`, and then generate the lockfile
            (see below).
            """
        )
        yield f"\n\nSee {doc_url('docs/python/overview/interpreter-compatibility')} for details."

    yield "\n\n"
    yield from (
        f"{fail}\n"
        for fail in _common_failure_reasons(validation.failure_reasons, maybe_constraints_file_path)
    )
    yield "To regenerate your lockfile, "
    yield f"run `{bin_name()} generate-lockfiles --resolve={resolve}`."
    yield f"\n\nSee {doc_url('docs/python/overview/third-party-dependencies')} for details.\n\n"


def rules():
    return collect_rules()
