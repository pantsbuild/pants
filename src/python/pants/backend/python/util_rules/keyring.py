# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import fcntl
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pants.backend.python.subsystems.repos import PythonRepos
from pants.base.build_environment import get_pants_cachedir
from pants.core.util_rules.system_binaries import AwkBinary, BashBinary, ShasumBinary
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.process import ProcessCacheScope
from pants.engine.rules import _uncacheable_rule, collect_rules, concurrently, implicitly
from pants.option.subsystem import _construct_subsystem

_FORGERY_DIR = ".keyring"
_KEYSTORE_DIR = ".keystore"


@dataclass(frozen=True)
class ForgedKeyring:
    digest: Digest
    bin_path: str | None


def _separate_authority_component(url: str) -> tuple[str, str] | None:
    """Function to separate the username from the repository URL.

    See here for details: https://datatracker.ietf.org/doc/html/rfc3986#section-3.2
    """

    parsed = urlparse(url)
    if not (parsed.hostname and parsed.username):
        return None

    # Create a new ParseResult without the username
    cleaned_netloc = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname

    # Reconstruct the URL without userinfo
    cleaned_url = urlunparse(
        (parsed.scheme, cleaned_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
    return cleaned_url, parsed.username


async def _populate_key_for_repo(
    key_store_path: Path, repo_url: str, username: str, password: bytes
) -> None:
    filepath = (
        key_store_path
        / hashlib.sha256(f"{repo_url}|{username}".encode(), usedforsecurity=False).hexdigest()
    )
    with open(filepath, "wb") as f:
        fd = f.fileno()
        try:
            fcntl.flock(fd, fcntl.LOCK_NB | fcntl.LOCK_EX)
        except OSError:
            # If this lock is already acquired, we can assume it is a concurrent run, so we can just return
            return
        f.write(password)
        fcntl.flock(fd, fcntl.LOCK_UN)


FORGERY_SCRIPT_FORMAT_STR = """\
#!{bash_path}

if [ "$1" != 'get' ]; then
    echo "Pant keyring-forgery script only supports 'get' operations, not '$1'" >&2
    exit 111
fi

cat {pants_cache_key_store}/$( printf '%s' "$2|$3" | {shasum_path} -a 256 | {awk_path} '{{print $1}}' )
exit $?
"""


@_uncacheable_rule
async def forge_keyring(
    python_repos: PythonRepos, bash: BashBinary, shasum: ShasumBinary, awk: AwkBinary
) -> ForgedKeyring:
    from pants.backend.python.subsystems.keyring import KeyringSubsystem
    from pants.backend.python.util_rules.pex import PexProcess, create_pex, setup_pex_process

    subsystem = await _construct_subsystem(KeyringSubsystem)
    if not subsystem.enabled:
        return ForgedKeyring(EMPTY_DIGEST, None)

    pants_cache_key_store = os.path.join(get_pants_cachedir(), _KEYSTORE_DIR)
    forged_script = FORGERY_SCRIPT_FORMAT_STR.format(
        bash_path=bash.path,
        shasum_path=shasum.path,
        awk_path=awk.path,
        pants_cache_key_store=pants_cache_key_store,
    )
    key_store_path = Path(pants_cache_key_store)
    key_store_path.mkdir(parents=True, exist_ok=True)
    keyring_pex, forged_script_digest = await concurrently(
        create_pex(subsystem.to_pex_request()),
        create_digest(
            CreateDigest(
                [
                    FileContent(
                        os.path.join(_FORGERY_DIR, "keyring"),
                        forged_script.encode(),
                        is_executable=True,
                    )
                ]
            )
        ),
    )
    repo_username_tuples = [
        repo_parts
        for repo in python_repos.indexes
        if (repo_parts := _separate_authority_component(repo))
    ]
    forgery_processes = await concurrently(
        setup_pex_process(
            PexProcess(
                keyring_pex,
                description=f"Forging keyring for {repo_url}",
                argv=("get", repo_url, username),
                cache_scope=ProcessCacheScope.PER_SESSION,
            ),
            **implicitly(),
        )
        for repo_url, username in repo_username_tuples
    )
    forgery_process_results = await concurrently(
        execute_process(forgery_process, **implicitly()) for forgery_process in forgery_processes
    )
    await concurrently(
        _populate_key_for_repo(key_store_path, repo_url, username, process_result.stdout)
        for (repo_url, username), process_result in zip(
            repo_username_tuples, forgery_process_results
        )
        if process_result.exit_code == 0
    )
    return ForgedKeyring(forged_script_digest, _FORGERY_DIR)


def rules():
    return collect_rules()
