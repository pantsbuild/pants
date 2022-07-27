---
title: "Kotlin"
slug: "kotlin"
excerpt: "Kotlin support for Pants."
hidden: false
createdAt: "2022-07-26T02:02:59.962Z"
updatedAt: "2022-07-26T02:02:59.962Z"
---

> 🚧 Kotlin support is alpha stage
>
> Kotlin support in Pants is still under active development, but currently supports compilation and testing. It has
> been tested with Kotlin v1.6.20.
>
> Please share feedback for what you need to use Pants with your Kotlin project by either
> [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose)
> or [joining our Slack](doc:community)!

> 📘 Example Kotlin repository
>
> Check out [github.com/pantsbuild/example-kotlin](https://github.com/pantsbuild/example-kotlin) to try a
> sample Pants project with Kotlin support.

# Overview

[Kotlin](https://kotlinlang.org/) is a programming language from Jetbrains that runs on the JVM and certain other
platforms. The Kotlin backend in Pants supports compilation, testing, and linting of
[Kotlin code for the JVM](https://kotlinlang.org/docs/server-overview.html). (The other Kotlin platforms including
[Kotlin Multiplatform Mobile](https://kotlinlang.org/docs/multiplatform.html) and
[Kotlin/JS](https://kotlinlang.org/docs/js-overview.html) are not currently supported, nor are there currently
any plans to do so.)

# Initial Setup

First, activate the Kotlin backend in `pants.toml` plus the `ktlint` backend if you would like to use
[`ktlint`](https://ktlint.github.io/) for code formatting and linting:

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.experimental.kotlin",
  
  # Activate the following backend if you want to use `ktlint` for code formatting and linting.
  "pants.backend.experimental.kotlin.lint.ktlint",
]
```

## Choosing JDK and Kotlin versions

Pants supports choosing the JDK and Kotlin versions per target in your repository. To reduce the amount of
boilerplate required, however, most users set repository-wide defaults in `pants.toml`, and then only override
them when necessary for particular targets.

### JDK

JDKs used by Pants are automatically fetched using [Coursier](https://get-coursier.io/), and are chosen using
the [`[jvm].jdk` option](doc:reference-jvm#section-jdk) to set a repository-wide default.

To override the default on a particular target, you can use the [`jdk=` field](doc:reference-kotlin_source#codejdkcode).
It can be useful to use the [`parametrize` builtin](doc:targets#parametrizing-targets) with the `jdk=` field,
particularly to run test targets under multiple JDKs.

### Kotlin version

The Kotlin version to use is configured on a resolve-by-resolve basis (see the "Third-party dependencies" section
below) using the [`[kotlin].version_for_resolve` option](doc:reference-kotlin#section-version_for_resolve). The
default Kotlin version for your repository will thus be whichever Kotlin version is configured for the "default"
resolve, which is configured by the [`[jvm].default_resolve` option](reference-jvm#section-default-resolve).

Each resolve must contain the following jars for the Kotlin runtime with the version matching the version specified
for the resolve in the `[kotlin].version_for_resolve` option:

- `org.jetbrains.kotlin:kotlin-stdlib`
- `org.jetbrains.kotlin:kotlin-reflect`
- `org.jetbrains.kotlin:kotlin-script-runtime`

To use multiple Kotlin versions in a repository, you would define multiple resolves, and then adjust
the [`resolve` field](doc:reference-kotlin_junit_test#coderesolvecode) of any targets which should be used with the
non-`default_resolve` resolve.

To cross-build a set of Kotlin targets for multiple Kotlin versions, you can use the
[`parametrize` builtin](doc:targets#parametrizing-targets) with the `resolve=` field of the target and its dependencies.

> 🚧 `jvm_artifact` targets for the Kotlin runtime must be explicitly defined.
>
> The Kotlin backend currently requires that a `jvm_artifact` target for each Kotlin runtime jars be present in any
> resolve used for Kotlin. If any of the required `jvm_artifact` targets are missing, Pants will error. Pants will
> automatically inject a dependency on the runtime into Kotlin targets. (These targets may be automatically supplied by
> Pants in a future version, but that is not currently implemented.)

## Dependencies

### First-party dependencies

In many cases, the dependencies of your first-party code are automatically inferred via
[dependency inference](https://blog.pantsbuild.org/automatically-unlocking-concurrent-builds-and-fine-grained-caching-on-the-jvm-with-dependency-inference/)
based on `import` statements in the code. If you do need to declare additional dependencies for any reason, you can do
so using Pants' [syntax for declaring dependencies for targets](doc:targets).

### Third-party dependencies and lockfiles

Third-party dependencies (i.e. those from repositories like [Maven central](https://search.maven.org/)) are also
automatically inferred via dependency inference, but must first be declared once per repository as 
[`jvm_artifact` targets](doc:reference-jvm_artifact):

```python BUILD
jvm_artifact(
    group="com.google.guava",
    artifact="guava",
    version="31.0.1-jre",
    # See the callout below for more information on the `packages` argument.
    packages=["com.google.common.**"],
)
```

Pants requires use of a lockfile for third-party dependencies. After adding or editing `jvm_artifact` targets, you
will need to update affected lockfiles by running `./pants generate-lockfiles`. The default lockfile is located at
`3rdparty/jvm/default.lock`, but it can be relocated (as well as additional resolves declared) via the
[`[jvm].resolves` option](doc:reference-jvm#section-resolves).

> 📘 Thirdparty symbols and the `packages` argument
>
> To efficiently determine which symbols are provided by third-party code (i.e., without hitting the network in order
> to compute dependencies in the common case), Pants relies on a static mapping of which artifacts provide which
> symbols, and defaults to treating each `jvm_artifact` as providing symbols within its `group`.
>
> The `packages` argument allows you to override which symbols a `jvm_artifact` provides. See the
> [`jvm_artifact` docs](doc:reference-jvm_artifact#codepackagescode) for more information.

### `resource` targets

To have your code [load files as "resources"](https://docs.oracle.com/javase/8/docs/technotes/guides/lang/resources.html):

1. Add a `resource` or `resources` target with the relevant files in the `source` / `sources` field, respectively.
2. Ensure that [an appropriate `source_root`](doc:source-roots) is detected for the `resources` target, in order to
   trim the relevant prefix from the filename to align with the layout of your JVM packages.
3. Add that target to the `dependencies` field of the relevant JVM target (usually the one that uses the JVM APIs to
   load the resource).

For example:

```toml pants.toml
[source]
# In order for the resource to be loadable as `org/pantsbuild/example/lib/hello.txt`,
# the `/src/jvm/ prefix needs to be stripped.
root_patterns = ["/src/*"]
```
```python src/jvm/org/pantsbuild/example/lib/BUILD
kotlin_sources(dependencies=[":hello"])

resources(name="hello", sources=["hello.txt"])
```
```java src/jvm/org/pantsbuild/example/lib/Loader.java
package org.pantsbuild.example.lib

import com.google.common.io.Resources

fun load() {
  ... = Resources.getResource(Loader.class, "hello.txt")
}
```
```text src/jvm/org/pantsbuild/example/lib/hello.txt
Hello world!
```

# Tasks

## Compile code

To manually check that sources compile, use `./pants check`:

```
# Check a single file
❯ ./pants check src/jvm/org/pantsbuild/example/lib/ExampleLib.kt

# Check files located recursively under a directory
❯ ./pants check src/jvm::

# Check the whole repository
❯ ./pants check ::
```

## Run tests

To run tests, use `./pants test`:

```
# Run a single test file
❯ ./pants test tests/jvm/org/pantsbuild/example/lib/ExampleLibTest.kt

# Test all files in and under a directory
❯ ./pants test tests/jvm::

# Test the whole repository
❯ ./pants test ::
```

The Kotlin backend currently supports JUnit tests specified using the `kotlin_junit_tests` target type.

## Lint and Format

[`ktlint`](https://ktlint.github.io/) can be enabled by adding the `pants.backend.experimental.kotlin.lint.ktlint`
backend to `backend_packages` in the `[GLOBAL]` section of `pants.toml`.

Once enabled, `lint` and `fmt` will check and automatically reformat your code:

```
# Format this directory and all subdirectories
❯ ./pants fmt src/jvm::

# Check that the whole project is formatted
❯ ./pants lint ::

# Format all changed files
❯ ./pants --changed-since=HEAD fmt
```

# Caveats

The Kotlin backend is currently experimental since many features are not implemented including:

- Kotlin modules. We would love to hear from Kotlin developers for advice on how modules are used and could
  be potentially supported by Pants.
- Non-JVM backends including [Kotlin Multiplatform Mobile](https://kotlinlang.org/docs/multiplatform.html) and
  [Kotlin/JS](https://kotlinlang.org/docs/js-overview.html)