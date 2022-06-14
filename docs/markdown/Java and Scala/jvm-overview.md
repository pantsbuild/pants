---
title: "Java and Scala overview"
slug: "jvm-overview"
excerpt: "Pants's support for Java and Scala."
hidden: false
createdAt: "2022-01-10T20:58:57.450Z"
updatedAt: "2022-05-03T23:52:32.836Z"
---
[block:callout]
{
  "type": "warning",
  "title": "Java and Scala support is beta stage",
  "body": "We are done implementing most functionality for Pants's Java and Scala support ([tracked here](https://github.com/pantsbuild/pants/projects/22)). However, there may be use cases that we aren't yet handling.\n\nPlease share feedback for what you need to use Pants with your JVM project by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:community)!"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Example Java and Scala repository",
  "body": "Check out [github.com/pantsbuild/example-jvm](https://github.com/pantsbuild/example-jvm) to try out Pants's Java and Scala support."
}
[/block]

[block:api-header]
{
  "title": "Initial setup"
}
[/block]
First, activate the relevant backends in `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  # Each backend can be used independently, so there is no need to enable Scala if you\n  # have a pure-Java repository (or vice versa).\n  \"pants.backend.experimental.java\",\n  \"pants.backend.experimental.scala\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Then run [`./pants tailor`](doc:create-initial-build-files) to generate BUILD files. This will create `java_sources` and `scala_sources` targets in every directory containing library code, as well as test targets like `scalatest_tests` and `junit_tests` for filenames that look like tests.

```
❯ ./pants tailor
Created src/jvm/org/pantsbuild/example/app/BUILD:
  - Add scala_sources target app
Created src/jvm/org/pantsbuild/example/lib/BUILD:
  - Add java_sources target lib
Created tests/jvm/org/pantsbuild/example/lib/BUILD:
  - Add scalatest_tests target lib
```

You can run `./pants list ::` to see all targets in your project:

```
❯ ./pants list
...
src/jvm/org/pantsbuild/example/app:app
src/jvm/org/pantsbuild/example/app/ExampleApp.scala
src/jvm/org/pantsbuild/example/lib:lib
src/jvm/org/pantsbuild/example/lib/ExampleLib.java
tests/jvm/org/pantsbuild/example/lib:lib
tests/jvm/org/pantsbuild/example/lib/ExampleLibSpec.scala
```

### Choosing JDK and Scala versions

Pants `2.11.x` adds support for choosing JDK and Scala versions per target in your repository, but to reduce the amount of boilerplate required, most users set repository-wide defaults in `pants.toml`, and then only override them when necessary for particular targets.

#### JDK

JDKs used by Pants are automatically fetched using [Coursier](https://get-coursier.io/), and are chosen using the [`[jvm].jdk` setting](doc:reference-jvm#section-jdk) to set a repository-wide default.

To override the default on a particular target, you can use the [`jdk=` field](doc:reference-java_source#codejdkcode). It can be useful to use the [`parametrize` builtin](doc:targets#parametrizing-targets) with the `jdk=` field, particularly to run test targets under multiple JDKs.

#### Scala version

The Scala version to use is configured on a resolve-by-resolve basis (see the "Third-party dependencies" section below) using the [`[scala].version_for_resolve` option](doc:reference-scala#section-version_for_resolve). The default Scala version for your repository will thus be whichever Scala version is configured for the "default" resolve, which is configured by the [`[jvm].default_resolve` option](reference-jvm#section-default-resolve).

To use multiple Scala versions in a repository, you would define multiple resolves, and then adjust the [`resolve` field](doc:reference-scalatest_test#coderesolvecode) of any targets which should be used with the non-`default_resolve` resolve.

To cross-build a set of Scala targets for multiple Scala versions, you can use the [`parametrize` builtin](doc:targets#parametrizing-targets) with the `resolve=` field of the target and its dependencies.
[block:callout]
{
  "type": "warning",
  "title": "A jvm_artifact for scala-library artifact is explicitly required.",
  "body": "The Scala backend currently requires that a `jvm_artifact` target for the `org.scala-lang:scala-library` Scala runtime be present in any resolve used for Scala. If such a jvm_artifact is missing, Pants will error. Pants will automatically inject a dependency on the runtime. (This target may be automatically supplied by Pants in a future version, but that is not currently implemented.)"
}
[/block]
### First-party dependencies

In many cases, the dependencies of your first-party code are automatically inferred via [dependency inference](https://blog.pantsbuild.org/automatically-unlocking-concurrent-builds-and-fine-grained-caching-on-the-jvm-with-dependency-inference/) based on your `import` statements. If you do need to declare additional dependencies for any reason, you can do so using Pants' [syntax for declaring dependencies for targets](doc:targets).

### Third-party dependencies and lockfiles

Third-party dependencies (i.e. those from repositories like [Maven central](https://search.maven.org/)) are also automatically inferred via dependency inference, but must first be declared once per repository as  [`jvm_artifact` targets](doc:reference-jvm_artifact):
[block:code]
{
  "codes": [
    {
      "code": "jvm_artifact(\n    group=\"com.google.guava\",\n    artifact=\"guava\",\n    version=\"31.0.1-jre\",\n    # See the callout below for more information on the `packages` argument.\n    packages=[\"com.google.common.**\"],\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
Pants requires use of a lockfile for thirdparty dependencies. After adding or editing `jvm_artifact` targets, you will need to update affected lockfiles by running `./pants generate-lockfiles`. The default lockfile is located at `3rdparty/jvm/default.lock`, but it can be relocated (as well as additional resolves declared) via the [`[jvm].resolves` option](doc:reference-jvm#section-resolves).
[block:callout]
{
  "type": "info",
  "body": "To efficiently determine which symbols are provided by thirdparty code (i.e., without hitting the network in order to compute dependencies in the common case), Pants relies on a static mapping of which artifacts provide which symbols, and defaults to treating each `jvm_artifact` as providing symbols within its `group`.\n\nThe `packages` argument allows you to override which symbols a `jvm_artifact` provides. See the [`jvm_artifact` docs](doc:reference-jvm_artifact#codepackagescode) for more information.",
  "title": "Thirdparty symbols and the `packages` argument"
}
[/block]
### `resource` targets

To have your code [load files as "resources"](https://docs.oracle.com/javase/8/docs/technotes/guides/lang/resources.html):

1. Add a `resource` or `resources` target with the relevant files in the `source` / `sources` field, respectively.
2. Ensure that [an appropriate `source_root`](doc:source-roots) is detected for the `resources` target, in order to trim the relevant prefix from the filename to align with the layout of your JVM packages.
3. Add that target to the `dependencies` field of the relevant JVM target (usually the one that uses the JVM APIs to load the resource).

For example:
[block:code]
{
  "codes": [
    {
      "code": "[source]\n# In order for the resource to be loadable as `org/pantsbuild/example/lib/hello.txt`,\n# the `/src/jvm/ prefix needs to be stripped.\nroot_patterns = [\"/src/*\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "java_sources(dependencies=[\":hello\"])\n\nresources(name=\"hello\", sources=[\"hello.txt\"])",
      "language": "python",
      "name": "src/jvm/org/pantsbuild/example/lib/BUILD"
    },
    {
      "code": "package org.pantsbuild.example.lib;\n\nimport com.google.common.io.Resources;\n\npublic class Loader {\n  public static String load() {\n    ... = Resources.getResource(Loader.class, \"hello.txt\");\n  }\n}\n",
      "language": "java",
      "name": "src/jvm/org/pantsbuild/example/lib/Loader.java"
    },
    {
      "code": "Hello world!",
      "language": "text",
      "name": "src/jvm/org/pantsbuild/example/lib/hello.txt"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Compile code"
}
[/block]
To manually check that sources compile, use `./pants check`:

```
# Check a single file
❯ ./pants check src/jvm/org/pantsbuild/example/lib/ExampleLib.java

# Check files located recursively under a directory
❯ ./pants check src/jvm::

# Check the whole repository
❯ ./pants check ::
```
[block:api-header]
{
  "title": "Run tests"
}
[/block]
To run tests, use `./pants test`:
```
# Run a single test file
❯ ./pants test tests/jvm/org/pantsbuild/example/lib/ExampleLibSpec.scala

# Test all files in a directory
❯ ./pants test tests/jvm::

# Test the whole repository
❯ ./pants test ::
```

You can also pass through arguments to the test runner with `--`, e.g.:
```
# Pass `-z hello` to scalatest in order to test a single method
❯ ./pants test tests/jvm/org/pantsbuild/example/lib/ExampleLibSpec.scala -- -z hello
```
[block:api-header]
{}
[/block]

[block:api-header]
{
  "title": "Lint and Format"
}
[/block]
`scalafmt` and `Google Java Format` can be enabled by adding the `pants.backend.experimental.scala.lint.scalafmt` and `pants.backend.experimental.java.lint.google_java_format` backends (respectively) to `backend_packages` in the `[GLOBAL]` section of `pants.toml`.

Once enabled, `lint` and `fmt` will check and automatically reformat your code:
```
# Format this directory and all subdirectories
❯ ./pants fmt src/jvm::

# Check that the whole project is formatted
❯ ./pants lint ::

# Format all changed files
❯ ./pants --changed-since=HEAD fmt
```