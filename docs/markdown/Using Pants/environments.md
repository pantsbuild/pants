---
title: "Environments: Cross-Platform or Remote Builds"
slug: "environments"
hidden: false
createdAt: "2022-10-03T21:39:51.235Z"
updatedAt: "2022-10-03T21:39:51.235Z"
---
Environments
============

By default, Pants will execute all sandboxed build work directly on localhost. But defining and using additional "environments" for particular targets allows Pants to transparently execute some or all of your build either:
1. locally in Docker containers
2. remotely via [remote execution](doc:remote-execution)
3. locally, but with a non-default set of environment variables and settings (such as for cross-building)

## Defining environments

Environments are defined using environment targets:

* [`local_environment`](doc:reference-local_environment) - Runs without containerization on localhost (which is also the default if no environment targets are defined).
* [`docker_environment`](doc:reference-docker_environment) - Runs in a cached container using the specified Docker image.
* [`remote_environment`](doc:reference-remote_environment) - Runs in a remote worker via [remote execution](doc:remote-execution) (possibly with containerization, depending on the server implementation).

Environment targets are given short, descriptive names using the [`[environments.names]` option](doc:reference-environments#names) (usually defined in `pants.toml`), which consuming targets use to refer to them in `BUILD` files. That might look like a `pants.toml` section and `BUILD` file (at the root of the repository in this case) containing:

```toml
[environments.names]
linux = "//:local_linux"
linux_docker = "//:local_busybox"
```

```python
local_environment(
  name="local_linux",
  compatible_platforms=["linux_x86_64"],
  fallback_environment="local_busybox",
  ..
)

docker_environment(
  name="local_busybox",
  platform="linux_x86_64",
  image="busybox:latest@sha256-abcd123...",
  ..
)
```

### Environment-aware options

Environment targets have fields (target arguments) which correspond to options which are marked "environment-aware". When an option is environment-aware, the value of the option that will be used in an environment can be overridden by setting the corresponding field value on the environment target for that environment. If an environment target does not set a value, it defaults to the value which is set globally via options values.

For example, the [`[python-bootstrap].search_path` option](doc:reference-python-bootstrap#search_path) is environment-aware, which is indicated in its help. It can be overridden for a particular environment by a corresponding environment target field, such as [the one on `local_environment`](doc:reference-local_environment#codepython_bootstrap_search_pathcode).

> 👍 See an option which should be environment-aware, but isn't?
>
> Environments are a new concept: if you see an option value which should be marked environment-aware but isn't, please definitely [file an issue](https://github.com/pantsbuild/pants/issues/new/choose)!

## Consuming environments

To declare which environment they should build with, many target types (but particularly "root" targets like tests or binaries) have an `environment=` field: for example, [`python_tests(environment=..)`](doc:reference-python_tests#codeenvironmentcode).

The `environment=` field may either:
1. refer to an environment by name
2. use a special `__local__` environment name, which resolves to any matching `local_environment` (see "Environment matching" below)

Test targets additionally have a `runtime_environment=` field (_TODO: see workflow example below, and implement_) which defaults to the value of the target's `environment=` field, but which can be set explicitly to indicate that a test should execute in a different environment than it was built in. This can be used to enable cross-building (where a test is built on one platform, but executed on another), or to explicitly provide tools or running services at test runtime which would not otherwise be available.

> 🚧 Environment compatibility
> 
> Currently, there is no static validation that a target's environment is compatible with its dependencies' environments -- only the implicit validation of the goals that you run successfully against those targets (`check`, `lint`, `test`, `package`, etc).
>
> As we gain more experience with how environments are used in the wild, it's possible that more static validation can be added: your feedback would be very welcome!

### Setting the environment on many targets at once

To use an environment everywhere in your repository (or only within a particular subdirectory, or with a particular target
type), you can use the [`__defaults__` builtin](doc:targets#field-default-values). For example, to use an environment named `my_default_environment` globally by default, you would add the following to a `BUILD` file at the root of the repository:
```python
__defaults__(all=dict(environment="my_default_environment"))
```
... and individual targets could override the default as needed.

### Environment matching

A single environment name may end up referring to different environment targets on different physical machines, or with different global settings applied: this is known as environment "matching".

* `local_environment` targets will match if their `compatible_platforms=` field matches localhost's platform.
* `docker_environment` targets will match [if Docker is enabled](doc:reference-global#docker_execution), and if their `platform=` field is compatible with localhost's platform.
* `remote_environment` targets will match [if Remote execution is enabled](doc:reference-global#remote_execution).

It a particular environment target _doesn't_ match, it can configure a `fallback_environment=` which will be attempted next. This allows for forming preference chains which are referred to by whichever environment name is at the head of the chain.

For example: a chain like "prefer remote execution if enabled, but fall back to local execution if the platform matches, otherwise use docker" might be configured via the targets:
```python
remote_environment(
  name="remote",
  fallback_environment="local",
  ..
)

local_environment(
  name="local",
  compatible_platforms=["linux_x86_64"],
  fallback_environment="docker",
)

docker_environment(
  name="docker",
  ..
)
```

In future versions, environment targets will gain additional predicates to control whether they match (for example: `local_environment` will likely gain a predicate that looks for the [presence or value of an environment variable](https://github.com/pantsbuild/pants/issues/17107). But in the meantime, it's possible to override which environments are matched for particular use cases by overriding their configured names: see the "Toggle use of an environment" workflow below for an example.

## Example workflows

### Enabling remote execution globally

`remote_environment` targets match unless the [`--remote-execution`](doc:reference-global#remote_execution) option is disabled. So to cause a particular environment name to use remote execution whenever it is enabled, you could define environment targets which tried remote execution first, and then fell back to local execution:

```python
remote_environment(
  name="remote_busybox",
  platform="linux_x86_64",
  extra_platform_properties={"container-image=busybox:latest"},
  fallback_environment="local",
)

local_environment(
  name="local",
  compatible_platforms=[...],
)
```

You'd then give your `remote_environment` target an unassuming name like "default":
```toml
[environments.names]
default = "//:remote_busybox"
local = "//:local"
```
... and use that environment by default with all targets. Users or consumers like CI could then toggle whether remote execution was used by setting `--remote-execution`.

> 🚧 Speculation of remote execution
> 
> The `2.15.x` series of Pants does not yet support ["speculating" remote execution](https://github.com/pantsbuild/pants/issues/8353) by racing it against another environment (usually local or docker). While we expect that this will be necessary to make remote execution a viable option for local execution on user's laptops (where network connections are less reliable), it is less critical for CI use-cases.

### Use a `docker_environment` to build the inputs to a `docker_image`

To build a `docker_image` target containing a `pex_binary` which uses native (i.e. compiled) dependencies on a `macOS` machine, you can configure the `pex_binary` to be built in a `docker_environment`.

You'll need a `docker_environment` which uses an image containing the relevant build-time requirements of your PEX. At a minimum, you'll need Python itself:
```python
docker_environment(
  name="python_bullseye",
  platform="linux_x86_64",
  image="python:3.9.14-slim-bullseye@sha256-abcd123...",
  ..
)
```

Next, mark your `pex_binary` target with this environment (with the name `python_bullseye`: see "Defining environments" above), and define a `docker_image` target depending on it.

```python
pex_binary(
  name="main",
  environment="python_bullseye",
)

docker_image(
    name="docker_image",
    instructions=[
        "FROM python:3.9.14-slim-bullseye@sha256-abcd123...",
        "ENTRYPOINT ["/main"]",
        "COPY examples/main.pex /main",
    ],
)
```

> 👍 Compatibility of `docker_environment` and `docker_image`
>
> Note that the Docker image used in your `docker_environment` does not need to match the base image of the `docker_image` targets that consume them: they only need to be compatible. This is because execution of build steps in a `docker_environment` occurs in an anonymous container, and only the required inputs are provided to the `docker_image` build.
>
> This means that your `docker_environment` can include things like compilers or other tools relevant to your build, without needing to manually use multi-stage Docker builds.

### Execute a test in Docker, while natively cross-building it

_TODO: Like https://github.com/pantsbuild/pants/issues/15764, but for tests._

_TODO: Give an example of using `environment=` vs `runtime_environment=` to use docker only for test execution, but not for building of thirdparty dependencies by using PEX to cross-build. This will require exposing options out of PEX to override (?) the target platform, and figuring out how that doesn't break `check` is an open question._

### Toggle use of an environment for some consumers

As mentioned above in "Environment matching", environment targets "match" based on their field values and global options. But if two environment targets would be ambiguous in some cases, or if you'd otherwise like to control what a particular environment name means (in CI, for example), you can override an environment name via options.

For example: if you'd like to use a particular `macOS` environment target locally, but override it for a particular use case in CI, you'd start by defining two `local_environment` targets which would usually match ambiguously:

```python
local_environment(
  name="macos_laptop",
  compatible_platforms=["macos_x86_64"],
)

local_environment(
  name="macos_ci",
  compatible_platforms=["macos_x86_64"],
)
```

... and then assign one of them a (generic) environment name in `pants.toml`:
```toml
[environments.names]
macos = "//:macos_laptop"
...
```

You could then _override_ that name definition in `pants.ci.toml` (note the use of the `.add` suffix, in order to preserve any other named environments):
```toml
[environments.names.add]
macos = "//:macos_ci"
```

