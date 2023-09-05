---
title: "Add lockfiles"
slug: "plugins-lockfiles-goal"
excerpt: "How to add lockfiles and the `generate-lockfiles` and `export` goals."
hidden: false
createdAt: "2023-08-013T00:00:00.000Z"
---
Lockfiles are a way to pin to exact versions of dependencies, often including hashes to guarantee integrity between the version pinned and the version downloaded.

This guide will walk you through implementing lockfiles, hooking them into the `generate-lockfiles` goal, and implementing the `export` goal which will allow you to export dependencies for use outside of Pants. It assumes that your language has a tool that supports generating and using lockfiles or that you have written code which does these. 

# 1. Expose your lockfiles to Pants

Create subclasses of `KnownUserResolveNamesRequest` to inform Pants about which resolves exist, and a subclass of `RequestedUserResolveNames` for Pants to request those resolves later. Implement the resolve-finding logic in a Rule from your subclass of `KnownUserResolveNamesRequest` to `KnownUserResolveNames`. Set `KnownResolveNames.requested_resolve_names_cls` to your subclass of `RequestedUserResolveNames`. 

```python
from pants.core.goals.generate_lockfiles import KnownUserResolveNamesRequest, RequestedUserResolveNames, KnownUserResolveNames
from pants.engine.rules import rule
from pants.engine.target import AllTargets


class KnownTerraformResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedTerraformResolveNames(RequestedUserResolveNames):
    pass


@rule
async def identify_user_resolves_from_terraform_files(
        _: KnownTerraformResolveNamesRequest,
        all_targets: AllTargets,
) -> KnownUserResolveNames:
    ...
    return KnownUserResolveNames(
        ...,
        requested_resolve_names_cls=RequestedTerraformResolveNames
    )
```

# 2. Connect resolve names to requests to generate lockfiles

Create a subclass of `GenerateLockfile`, (TODO: Why). Then create a rule from your subclass of `RequestedUserResolveNames` to `UserGenerateLockfiles`. Pants will use this rule to convert from a user's request to export a resolve by name into the information needed to export the resolve.

```python
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformDeploymentTarget
from pants.core.goals.generate_lockfiles import GenerateLockfile, UserGenerateLockfiles
from pants.engine.rules import rule


@dataclass(frozen=True)
class GenerateTerraformLockfile(GenerateLockfile):
    target: TerraformDeploymentTarget


@rule
async def setup_user_lockfile_requests(
        requested: RequestedTerraformResolveNames,
) -> UserGenerateLockfiles:
    ...
    return UserGenerateLockfiles(
        [
            GenerateTerraformLockfile(
                ...
            )
        ]
    )
```

# 3. Generate lockfiles

Create a rule from your subclass of `GenerateLockfile` to `GenerateLockfileResult`. This rule generates the lockfile. In the common case that you're running a process to generate this lockfile, you can use the `Process.output_files` to gather those files from the execution sandbox.

```python
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import rule


@rule
async def generate_lockfile_from_sources(
        request: GenerateTerraformLockfile,
) -> GenerateLockfileResult:
    ...

    result = await Get(
        ProcessResult,
        TerraformProcess(...),
    )

    return GenerateLockfileResult(result.output_digest, request.resolve_name, request.lockfile_dest)

```

# 4. Register rules

At the bottom of the file, let Pants know what your rules and types do. Update your plugin's `register.py` to tell Pants about them/

```python pants-plugins/terraform/lockfiles.py


from pants.core.goals.generate_lockfiles import GenerateLockfile, KnownUserResolveNamesRequest, RequestedUserResolveNames
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GenerateTerraformLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownTerraformResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedTerraformResolveNames),
    )
```

```python pants-plugins/terraform/register.py
from terraform import lockfiles

def rules():
    return [
        ...,
        *lockfiles.rules()
    ]
```

# 5. Use lockfiles for fetching dependencies

If you have a tool that supports lockfiles, the easiest way to get the lockfile to it is to simply use a glob to pull the file into a digest.

```python
from pathlib import Path

from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import rule


@rule
async def init_terraform(request: TerraformInitRequest) -> TerraformInitResponse:
    ...
    Get(Snapshot, PathGlobs([(Path(request.root_module.address.spec_path) / ".terraform.lock.hcl").as_posix()])),
```

TODO: You can also reference this in the dependency inference. This dependency link will result in the lockfile being imported through the standard dependency request, and it will also cause all dependent source files to be marked as transitively changed
