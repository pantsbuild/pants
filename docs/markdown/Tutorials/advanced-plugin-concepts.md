---
title: "Advanced plugin concepts"
slug: "advanced-plugin-concepts"
excerpt: "Learning advanced concepts for writing plugins."
hidden: false
createdAt: "2022-02-07T05:44:28.620Z"
---
# Introduction

In this tutorial, we continue from where we've left in the [previous tutorial](doc:create-a-new-goal). Having now a complete goal with a custom target, we are ready to make certain improvements and learn more advanced concepts that you would likely find useful when working on your own plugins.

## Adding a custom `source` field

In the first tutorial, to keep things simple, we used the default `SingleSourceField` class for our `source` field where we provided the path to the `VERSION` file. We could have added [a custom field](https://www.pantsbuild.org/docs/target-api-new-fields) to provide a file path, however, when using the `source` field, you get a few features for free such as setting the `default` value and `expected_file_extensions`. Furthermore, with the `source` field, thanks to the [`unmatched_build_file_globs`](https://www.pantsbuild.org/docs/reference-global#unmatched_build_file_globs) option, you won't need to provide custom logic to handle errors when path globs do not expand to any files in your repository.

Let's modify our `myapp/BUILD` file:

```
version_file(
    name="main-project-version",
    source="non-existing-file",
)
```

and run the `project-version` goal:

```
$ pants project-version myapp:
...
[WARN] Unmatched glob from myapp:main-project-version's `source` field: "myapp/non-existing-file"
[ERROR] 1 Exception encountered:

  InvalidFieldException: The 'source' field in target myapp:main-project-version must have 1 file, but it had 0 files.
...
```

It is possible to adjust how Pants handle unmatched globs to prevent this type of issue:

```
$ PANTS_UNMATCHED_BUILD_FILE_GLOBS=error pants project-version myapp:
[ERROR] 1 Exception encountered:
  Exception: Unmatched glob from myapp:main-project-version's `source` field: "myapp/non-existing-file"
```

We would likely want to use the same name for the version file (`VERSION`) throughout the repo for consistency, so we should probably set a default value for the target to reduce the amount of boilerplate in the `BUILD` files. To change a default value, we have to subclass the original field. Visit [customizing fields through subclassing](https://www.pantsbuild.org/docs/target-api-concepts#customizing-fields-through-subclassing) to learn more.

```python pants-plugins/project_version/target_types.py
from pants.engine.target import COMMON_TARGET_FIELDS, SingleSourceField, Target

class ProjectVersionSourceField(SingleSourceField):
    help = "Path to the file with the project version."
    default = "VERSION"
    required = False

class ProjectVersionTarget(Target):
    alias = "version_file"
    core_fields = (*COMMON_TARGET_FIELDS, ProjectVersionSourceField)
    help = "A project version target representing the VERSION file."
```

You may have noticed that we have decided to override the `help` property to show more relevant information than the default help message:

```
$ pants help version_file          
`version_file` target
---------------------

A project version target representing the VERSION file.

Activated by project_version
Valid fields:

...
source
    type: str | None
    default: 'VERSION'

    Path to the file with the project version.
...
```

Having a dedicated source field will let us filter the targets based on the fact that they have a `ProjectVersionSourceField` field instead of checking what their alias is. This means we can refactor how we collect the relevant targets from:

```python
targets = [tgt for tgt in targets if tgt.alias == ProjectVersionTarget.alias]
```

to

```python
targets = [tgt for tgt in targets if tgt.has_field(ProjectVersionSourceField)]
```

Using own classes via subclassing will also help with refactoring if you decide to deprecate the target alias in order to rename it. In a more advanced scenario, other plugins may import the `ProjectVersionSourceField` field and use it in their own custom targets, so that `project-version` specific behavior would still apply to those targets as well. 

## Ensuring a version follows a semver convention

With the current implementation, we have simply returned the contents of the file as is. We may want to add some validation, for instance, to check that a version string follows a semver convention. Let's learn how to [bring a 3rd party Python package](https://www.pantsbuild.org/docs/plugins-overview#thirdparty-dependencies), namely, [packaging](https://pypi.org/project/packaging/), into our plugin to do that! 

To start depending on the `packaging` package in our in-repo plugin, we must extend the `pants.toml` file:

```toml
[GLOBAL]
plugins = ["packaging==22.0"]
```

Now, let's raise an exception if it isn't possible to construct an instance of the `Version` class:

```python
from packaging.version import Version, InvalidVersion
from project_version.target_types import ProjectVersionTarget, ProjectVersionSourceField

class InvalidProjectVersionString(ValueError):
    pass

@goal_rule
async def goal_show_project_version(targets: Targets) -> ProjectVersionGoal:
    targets = [tgt for tgt in targets if tgt.has_field(ProjectVersionSourceField)]
    results = await MultiGet(
        Get(ProjectVersionFileView, ProjectVersionTarget, target) for target in targets
    )
    for result in results:
        try:
           _ = Version(result.version)
        except InvalidVersion:
            raise InvalidProjectVersionString(f"Invalid version string '{result.version}' from '{result.path}'")
    ...
```

To test this behavior, let's set a bogus version and see our goal in action!

```
$ cat myapp/VERSION
x.y.z

$ pants project-version myapp:
[ERROR] 1 Exception encountered:

    InvalidProjectVersionString: Invalid version string 'x.y.z' from 'myapp/VERSION'
```

## Exploring caching

When you have run the goal a few times, you may have noticed that sometimes the command takes a few seconds to complete, and sometimes it completes immediately. If that's the case, then you have just seen [Pants caching](https://www.pantsbuild.org/docs/rules-api-tips#fyi-caching-semantics) working! Because we use Pants engine to read the `VERSION` file, it copies it into the cache. Pants knows that when the command is re-run, if there are no changes to the Python source code or the `VERSION` file, there's no need to re-run the code because the result is guaranteed to stay the same.

If your plugin uses 3rd party Python packages dependencies, it can be worth checking whether the package has any side effects such as reading from the filesystem since this won't let you take full advantage of the Pants engine's caching mechanism. Keep in mind that the commands you run via Pants may be cancelled or retried any number of times, so ideally any side effects should be [idempotent](https://en.wikipedia.org/wiki/Idempotence). That is, it should not matter if it is run once or several times.

You can confirm that cache is being used by adding [log statements](https://www.pantsbuild.org/docs/rules-api-logging). When run for the first time, the logging messages will show up; on subsequent runs, they won't because the code of the rules won't be executed.

## Showing output as JSON

We have so far shown the version string as part of the `ProjectVersionFileView` class:

```
$ pants project-version myapp: 
ProjectVersionFileView(path='myapp/VERSION', version='0.0.1')
```

To be able to pipe the output of our command, it may make sense to emit the format in a parseable structure instead of plain text. Pants goals come with lots of options that can adjust their behavior, and this is true for custom goals as well. Let's [add a new option](https://www.pantsbuild.org/docs/rules-api-subsystems) for our goal, so that the version information would be shown as a JSON object.

Adding a new option is trivial and is done in the subsystem:

```python
class ProjectVersionSubsystem(GoalSubsystem):
    name = "project-version"
    help = "Show representation of the project version from the `VERSION` file."

    as_json = BoolOption(
        default=False,
        help="Show project version information as JSON.",
    )
```

To use a subsystem in the goal rule (where we show the version in the console), we need to request it as a parameter:

```python
import json

@goal_rule
async def goal_show_project_version(
    console: Console, project_version_subsystem: ProjectVersionSubsystem
) -> ProjectVersionGoal:
    ...
    if project_version_subsystem.as_json:
        console.print_stdout(json.dumps(dataclasses.asdict(result)))
    else:
        console.print_stdout(str(result))
```

Let's run our goal with the new `--as-json` flag:

```
$ pants project-version --as-json myapp: | jq
{
  "path": "myapp/VERSION",
  "version": "0.0.1"
}
```

## Automating generation of `project_version` targets

Pants provides a way to automate generation of standard targets using the [`tailor`](https://www.pantsbuild.org/docs/reference-tailor) goal. If a monorepository has many projects, each containing a `VERSION` file, it might be useful to generate `version_file` targets in every directory where the relevant files are found. This is what Pants does, for instance, when Docker backend is enabled, and you have `Dockerfile` files in the codebase. To make this work for our use case, however, we need to introduce the `tailor` goal to the `VERSION` files.

We've reached the moment when the documentation won't be of help: there are no instructions on how to extend the `tailor` goal. In a situation like this, it may be worth exploring the Pants codebase to see how this was done in other plugins that are part of Pants. Once you find a piece of code that looks like it does what you want, you can copy it and tweak it to better suit your needs. For our use case, the code used in [generation of C++ source targets](https://github.com/pantsbuild/pants/blob/672ca1d662c76f2567e432347deee8949c14d35d/src/python/pants/backend/cc/goals/tailor.py) may get handy. After making a few changes, we have a new rule we can place in a new file:

```python pants-plugins/project_version/tailor.py
from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.util.dirutil import group_by_dir
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from project_version.target_types import ProjectVersionTarget


@dataclass(frozen=True)
class PutativeProjectVersionTargetsRequest(PutativeTargetsRequest):
    pass


@rule(desc="Determine candidate project_version targets to create")
async def find_putative_targets(
    req: PutativeProjectVersionTargetsRequest,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    all_project_version_files = await Get(Paths, PathGlobs, req.path_globs("VERSION"))
    unowned_project_version_files = set(all_project_version_files.files) - set(
        all_owned_sources
    )
    classified_unowned_project_version_files = {
        ProjectVersionTarget: unowned_project_version_files
    }

    putative_targets = []
    for tgt_type, paths in classified_unowned_project_version_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    ProjectVersionTarget,
                    path=dirname,
                    name="project-version-file",
                    triggering_sources=sorted(filenames),
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeProjectVersionTargetsRequest),
    ]
```

In this file, we use an advanced feature of Pants, [union rules](https://www.pantsbuild.org/docs/rules-api-unions):

```python
def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeProjectVersionTargetsRequest),
    ]
```

When the `tailor` goal is run, the build graph is analyzed to see when `PutativeTargetsRequest` is needed, i.e. to find out if there are any files (yet unknown to Pants) that look like they could potentially be made targets. For instance, if there is a `requirements.txt` file, a `python_requirement` target is created and when there is a Python `test_` module, a `python_test` target is created. To be able to customize the `tailor` goal (to allow generation of custom targets), we need to "extend" the build graph. That is, we ask Pants to also run our rule when searching for files that maybe should have a target created.

We also have to make sure that the new rule is collected:

```python pants-plugins/project_version/register.py
...
def rules():
    return [*project_version_rules.rules(), *tailor_rules.rules()]
```

Let's remove existing `version_file` target from the `myapp/BUILD` file and run the `tailor` goal:

```
$ pants tailor ::        
Created myapp/BUILD:
  - Add version_file target project-version-file 
```

If you have multiple projects, being able to generate the targets automatically may save time. You would also likely want to run the `tailor` goal in the check mode to confirm that new projects created have a `version_file` target. Remove the `version_file` target from the `myapp/BUILD` file and re-run the `tailor` goal:

```
$ pants tailor --check ::                         
Would create myapp/BUILD:
  - Add version_file target project-version-file

To fix `tailor` failures, run `pants tailor`.
```

## Running system tools

Pants lets you [run system applications](https://www.pantsbuild.org/docs/rules-api-installing-tools) your plugin may need. For our use case, we can assume that Git is installed and can be run from the `/usr/bin/git`. If there's a `VERSION` file in the root of the repository representing the final artifact version (in case of a monolith), we could use Git to confirm that the version string matches the latest tag the repository was tagged with.

We can create a new rule:

```python
class GitTagVersion(str):
    pass

@rule
async def get_git_repo_version(buildroot: BuildRoot) -> GitTagVersion:
    git_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="git",
            search_path=["/usr/bin", "/bin"],
        ),
    )
    git_bin = git_paths.first_path
    if git_bin is None:
        raise OSError("Could not find 'git'.")
    git_describe = await Get(
        ProcessResult,
        Process(
            argv=[git_bin.path, "-C", buildroot.path, "describe", "--tags"],
            description="git describe --tags",
        ),
    )
    return GitTagVersion(git_describe.stdout.decode().strip())
```

and then use this rule in the main goal rule:

```python
class ProjectVersionGitTagMismatch(ValueError):
    pass

@goal_rule
async def goal_show_project_version(...) -> ProjectVersionGoal:
    ...
    git_repo_version = await Get(GitTagVersion)
    ...
    if git_repo_version != result.version:
        raise ProjectVersionGitTagMismatch(
            f"Project version string '{result.version}' from '{result.path}' "
            f"doesn't match latest Git tag '{git_repo_version}'"
        )
```

Let's modify our `VERSION` file to have a version different from what we have tagged our repository with:

```
$ git tag 0.0.1
$ git describe --tags
0.0.1
$ cat myapp/VERSION
0.0.2

$ pants project-version --as-json myapp:
12:40:17.02 [INFO] Initializing scheduler...
12:40:17.14 [INFO] Scheduler initialized.
12:40:17.18 [ERROR] 1 Exception encountered:

  ProjectVersionGitTagMismatch: Project version string '0.0.2' from 'myapp/VERSION' doesn't match latest Git tag '0.0.1'
```

Now, let's tag our repository with another tag and update our `VERSION` file:

```
$ git tag --delete 0.0.1
Deleted tag '0.0.1' (was 006f320) 
$ git tag 0.0.2
$ git describe --tags
0.0.2
$ cat myapp/VERSION
0.0.1

$ pants project-version --as-json myapp:
{"path": "myapp/VERSION", "version": "0.0.1"}
```

Pants is happy, but clearly something is wrong as our Git tag version doesn't match the `myapp/VERSION` version! If you update your `myapp/VERSION` with another version, say, `0.0.3`, we get an error, but this time, the shown Git tag is wrong:

```
$ cat myapp/VERSION
0.0.3

$ pants project-version --as-json myapp:
[ERROR] 1 Exception encountered:

  ProjectVersionGitTagMismatch: Project version string '0.0.3' from 'myapp/VERSION' doesn't match latest Git tag '0.0.1'
```

This happens because of how the Pants cache works. Modifying our repository tags doesn't qualify for the changes that should invalidate the cache. It is not safe to [cache the `Process` runs](https://www.pantsbuild.org/docs/rules-api-process) and since we know that Git will access the repository (that is outside the sandbox), we should change its cacheability using the `ProcessCacheScope` parameter so that our Git call would run once per run of Pants.

```python
git_describe = await Get(
    ProcessResult,
    Process(
        argv=[git_bin.path, "-C", buildroot.path, "describe", "--tags"],
        description="git describe --tags",
        cache_scope=ProcessCacheScope.PER_SESSION,
    ),
)
```

Let's add another option so that we can control whether Git tag should be retrieved:

```python
class ProjectVersionSubsystem(GoalSubsystem):
    name = "project-version"
    help = "Show representation of the project version from the `VERSION` file."
    
    ...
    match_git = BoolOption(
        default=False,
        help="Check Git tag of the repository matches the project version.",
    )
```

Keep in mind that once you've declared [custom options in the plugin's subsystem](https://www.pantsbuild.org/docs/options#setting-options), they can be set in the `pants.toml` file just like any standard Pants options.

If you know that your Git tag may be different from the project version stored in the `VERSION` file and that you would always want the output to be in the JSON format, you can set these options in the `pants.toml` file for visibility (and to avoid setting them via command line flags):

```toml
[project-version]
as_json = true
match_git = false
```

## Putting it all together

We have now extended the plugin with extra functionality:

```
$ pants project-version myapp:                      
[INFO] Initializing scheduler...
[INFO] Scheduler initialized.
{"path": "myapp/VERSION", "version": "0.0.1"}
```

Let's get all of this code in one place:

```python pants-plugins/project_version/register.py
from typing import Iterable

import project_version.rules as project_version_rules
import project_version.tailor as tailor_rules
from pants.engine.target import Target
from project_version.target_types import ProjectVersionTarget


def target_types() -> Iterable[type[Target]]:
    return [ProjectVersionTarget]


def rules():
    return [*project_version_rules.rules(), *tailor_rules.rules()]
```
```python pants-plugins/project_version/rules.py
import dataclasses
import json
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version
from pants.base.build_root import BuildRoot
from pants.core.util_rules.system_binaries import BinaryPathRequest, BinaryPaths
from pants.engine.console import Console
from pants.engine.fs import DigestContents
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
)
from pants.option.option_types import BoolOption
from project_version.target_types import ProjectVersionSourceField, ProjectVersionTarget


@dataclass(frozen=True)
class ProjectVersionFileView:
    path: str
    version: str


@rule
async def get_project_version_file_view(
    target: ProjectVersionTarget,
) -> ProjectVersionFileView:
    sources = await Get(HydratedSources, HydrateSourcesRequest(target[SourcesField]))
    digest_contents = await Get(DigestContents, Digest, sources.snapshot.digest)
    file_content = digest_contents[0]
    return ProjectVersionFileView(
        path=file_content.path, version=file_content.content.decode("utf-8").strip()
    )


class ProjectVersionSubsystem(GoalSubsystem):
    name = "project-version"
    help = "Show representation of the project version from the `VERSION` file."

    as_json = BoolOption(
        default=False,
        help="Show project version information as JSON.",
    )
    match_git = BoolOption(
        default=False,
        help="Check Git tag of the repository matches the project version.",
    )


class ProjectVersionGoal(Goal):
    subsystem_cls = ProjectVersionSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


class InvalidProjectVersionString(ValueError):
    pass


class ProjectVersionGitTagMismatch(ValueError):
    pass


class GitTagVersion(str):
    pass


@goal_rule
async def goal_show_project_version(
    console: Console,
    targets: Targets,
    project_version_subsystem: ProjectVersionSubsystem,
) -> ProjectVersionGoal:
    targets = [tgt for tgt in targets if tgt.has_field(ProjectVersionSourceField)]
    results = await MultiGet(
        Get(ProjectVersionFileView, ProjectVersionTarget, target) for target in targets
    )
    if project_version_subsystem.match_git:
        git_repo_version = await Get(GitTagVersion)

    for result in results:
        try:
            _ = Version(result.version)
        except InvalidVersion:
            raise InvalidProjectVersionString(
                f"Invalid version string '{result.version}' from '{result.path}'"
            )
        if project_version_subsystem.match_git:
            if git_repo_version != result.version:
                raise ProjectVersionGitTagMismatch(
                    f"Project version string '{result.version}' from '{result.path}' "
                    f"doesn't match latest Git tag '{git_repo_version}'"
                )

        if project_version_subsystem.as_json:
            console.print_stdout(json.dumps(dataclasses.asdict(result)))
        else:
            console.print_stdout(str(result))

    return ProjectVersionGoal(exit_code=0)


@rule
async def get_git_repo_version() -> GitTagVersion:
    git_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="git",
            search_path=["/usr/bin", "/bin"],
        ),
    )
    git_bin = git_paths.first_path
    if git_bin is None:
        raise OSError("Could not find 'git'.")
    git_describe = await Get(
        ProcessResult,
        Process(
            argv=[git_bin.path, "-C", buildroot.path, "describe", "--tags"],
            description="git describe --tags",
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )
    return GitTagVersion(git_describe.stdout.decode().strip())


def rules():
    return collect_rules()
```
```python pants-plugins/project_version/tailor.py
from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from project_version.target_types import ProjectVersionTarget


@dataclass(frozen=True)
class PutativeProjectVersionTargetsRequest(PutativeTargetsRequest):
    pass


@rule(desc="Determine candidate version_file targets to create")
async def find_putative_targets(
    req: PutativeProjectVersionTargetsRequest,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    all_project_version_files = await Get(Paths, PathGlobs, req.path_globs("VERSION"))
    unowned_project_version_files = set(all_project_version_files.files) - set(
        all_owned_sources
    )
    classified_unowned_project_version_files = {
        ProjectVersionTarget: unowned_project_version_files
    }

    putative_targets = []
    for tgt_type, paths in classified_unowned_project_version_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    ProjectVersionTarget,
                    path=dirname,
                    name="project-version-file",
                    triggering_sources=sorted(filenames),
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeProjectVersionTargetsRequest),
    ]
```
```python pants-plugins/project_version/target_types.py
from pants.engine.target import COMMON_TARGET_FIELDS, SingleSourceField, Target


class ProjectVersionSourceField(SingleSourceField):
    alias = "source"
    help = "Path to the file with the project version."
    default = "VERSION"
    required = False


class ProjectVersionTarget(Target):
    alias = "version_file"
    core_fields = (*COMMON_TARGET_FIELDS, ProjectVersionSourceField)
    help = "A project version target representing the VERSION file."
```

There are a few more things left to do, for example, we haven't written any tests yet. This is what we'll do in the next tutorial!
