# Haskell plugin

## Table of contents

## Summary

There are three different levels of code organization and distribution in
Haskell:

* **Source files** - Managed by the `ghc` compiler
  files
* **Packages** - A set of source files, managed by the `cabal` tool
* **Projects** - A set of packages, managed by the `stack` tool

This Haskell plugin provides a `pants` interface to the **project** layer.

This plugin may eventually provide an interface to the **package** layer, but
does not yet do so.

The **source file** layer is indirectly managed by the project and package
layers.

If you are new to Haskell, read the Background section, which gives an overview
of the Haskell build tooling.

The Implementation section explains how this plugin wraps the Haskell build
tools in more detail.

The Example Usage section walks through what the end user experience would be
like

* [Background](#background)
  * [`ghc`](#ghc)
  * [Package creation](#package-creation)
  * [Package consumption](#package-consumption)
  * [Package caches](#package-caches)
* [Implementation](#implementation)
  * [Targets](#targets)
  * [Paths and working directories](#paths-and-working-directories)
  * [Resolvers](#resolvers)
  * [Bootstrapping `stack`](#bootstrapping-stack)
  * [Goals](#goals)
* [Example Usage](#example-usage)
  * [Stackage packages](#stackage-packages)
  * [Hackage packages](#hackage-packages)
  * [Remote source packages](#remote-source-packages)
  * [Local source project](#local-source-project)
  * [New local project](#new-local-project)
  * [Project sharing](#project-sharing)

## Background

### `ghc`

If you are familiar with C, `ghc` is analogous to a C compiler like `gcc` or
`clang`: source files go in one end and executables or object code come out the
other end.  The only difference is that when `ghc` emits object code it also
emits an additional "interface file" (with a `*.hi` suffix) which exports some
source code for cross-module inlining, specialization, and optimization.

Here's an example of generating object code and an interface file:

```bash
$ cat Test.hs
module Test where
foo = "An example string"

$ ghc -O2 Test.hs
[1 of 1] Compiling Test             ( Test.hs, Test.o )

$ ls
Test.hi Test.hs Test.o
```

... and here's an example of generating an executable:

```bash
$ cat HelloWorld.hs
main = putStrLn "Hello, world!"

$ ghc -O2 HelloWorld.hs
[1 of 1] Compiling Main             ( HelloWorld.hs, HelloWorld.o )
Linking HelloWorld ...

$ ls
HelloWorld    HelloWorld.hi HelloWorld.hs HelloWorld.o

$ ./HelloWorld
Hello, world!
```

By default, GHC executables are native binaries that are *mostly* statically
linked, meaning that all the Haskell code is statically linked, but some
libraries that the Haskell runtime requires are not (specifically `libc`,
`libpthread`, and `libgmp`).  You can optionally fully statically link an
executable (i.e. like in Go), or dynamically link Haskell libraries, but neither
of those are the default behavior.

`ghc` is a low-level tool that is only used for small, ad-hoc projects because
`ghc` does not do any formal dependency management.  For larger projects you
will typically use the `stack` tool (Keep reading to learn more about `stack`).

Haskell code is also not distributed at the granularity of individual source
files or object code.  Instead, Haskell uses a package system like other
languages, which is the subject of the next section.

### Package creation

Packages are the atomic unit of code distribution in Haskell.  A minimal Haskell
package is:

* a collection of source files
* a `*.cabal` file containing package meta-data
* a `LICENSE` file

Here is an example package layout:

```
mypackage/
|-- LICENSE
|-- mypackage.cabal
`-- src/
    `-- Foo/
        `-- Bar.hs
```

... where `mypackage.cabal` might look like this:

```
name:                minimal-example-library
version:             1.0.0
description:         Paradigm disruptor
license:             BSD
license-file:        LICENSE
author:              Alice
maintainer:          alice@example.com
build-type:          Simple
cabal-version:       >=1.10

library
    hs-source-dirs:    src
    build-depends:     base       >= 4.5 && < 4.8
                     , containers >= 0.5 && < 0.6
    exposed-modules:   Foo.Bar
```

... and `Foo/Bar.hs` might look like this:

```haskell
module Foo.Bar where

import Data.Set (Set, fromList)  -- This module comes from `containers`

baz :: Set Int
baz = fromList [1, 7, 4]
```

This package exports a Haskell module named `Foo.Bar`.  The module name must
match the directory/file layout underneath the source tree.

The `build-depends` section of the `*.cabal` file is where you specify
package dependencies.  For example, when we add `containers` as a build
dependency we can import any module exported by the `containers` package (and
`Data.Set` is one such module).  The package name does not need to match the
name of the modules it exports.

There are three main ways that you can make your package code available to
others in increasing order of diligence:

* The simplest approach is to provide a source distribution of your package
* You can also upload the package to Hackage under a name and version number
* If you are thrice diligent you can optionally add any package on Hackage to
  Stackage

The more diligent you are the more easily others can depend on your package.

By default, all dependencies are downloaded from Hackage unless you explicitly
override them to point to other non-Hackage sources

One example of a non-Hackage source is a package hosted only on Github such as
the following `pipes-tar` package:

[https://github.com/ocharles/pipes-tar](https://github.com/ocharles/pipes-tar)

Hackage is a more formal package repository.  When you upload a package to
Hackage you specify a package name and version and then any other package can
depend on your package by specifying the same name and version number in their
`*.cabal` file.  Users can also specify version ranges for their dependencies
instead of fixed versions.

You can see an example package named `attoparsec` hosted on Hackage here:

[https://hackage.haskell.org/package/attoparsec](https://hackage.haskell.org/package/attoparsec)

Stackage on the other hand is not a package repository; it's actually a
"version set repository".  Stackage keeps track of package versions that build
correctly together using a giant automated "mono-build" (i.e. one giant Haskell
project that attempts to simultaneously build all packages tracked by Stackage).
If a maintainer adds their package to Stackage then they are on the hook to
update their own package to continue building correctly within this mono-build.
Periodically the latest package versions that build together successfully are
frozen and released as version set snapshots known as "resolvers".  Stackage
provides both nightly snapshots named `"nightly-YYYY-MM-DD"` or less
frequent long-term snapshots named `"lts-X.Y"`.

You can see what an example Stackage snapshot looks like here:

[https://www.stackage.org/lts-3.1/cabal.config](https://www.stackage.org/lts-3.1/cabal.config)

### Package consumption

Every Haskell package must specify the names of direct dependencies.  To be
precise, if your source code imports some module named `Foo.Bar` then you must
depend on the package that exports `Foo.Bar` within your `*.cabal` file.  You do
not need to specify transitive dependencies if you don't directly import the
modules they provide.

For each dependency you can specify either:

* a fixed version,
* a version range, or:
* no constraint at all

Haskell also imposes the restriction that you cannot have two versions of the
same package in a project's dependency graph.  I'm oversimplifying a bit, but
this is mostly true.

For a very long time, the idiomatic solution to dependency resolution was for
packages to specify their dependencies as version ranges.  Then the
`cabal-install` project management tool would use an SMT solver to select a
version for each package in the dependency graph that satisfied all version
constraints.

This version range and SMT-solver approach led to what is popularly known as
"cabal hell", which referred to the irreproducibility of Haskell builds.  A
package that initially built successfully could fail to build a year later.

To correct this problem the company FPComplete (the Haskell version of Scala's
TypeSafe) released a new project management tool named `stack`, which takes a
different approach to dependency resolution:

* Dependency versions are specified at the project level, not the package level
* A project fixes the versions of every package in the dependency graph and
  also fixes the version of compiler used to build the project

The project-level metadata is stored in a `stack.yaml` file.  Here's an example
of a minimal `stack.yaml` file that we can add to the above minimal package to
turn our package into a project:

```
flags: {}  # Ignore this field for now
packages:
- '.'
extra-deps: []
resolver: lts-3.1
```

The meaning of the fields are:

* `resolver`: Lock in versions for dependencies on Stackage
* `extra-deps`: Lock in versions for dependencies on Hackage but not on Stackage
* `packages`: All source dependencies for this project

Our example package had only one dependency (i.e. `containers`) and that
dependency is already constrained by the `lts-3.1` resolver, so we didn't need
to specify any other information within our `stack.yaml` file.

`stack` was designed to be backwards compatible with the prevous `cabal-install`
build tool and workflow.  This means that there is some duplication of
information: you can constrain a dependency version both at the package level
and the project level.  The best practice for open source is to do both to
ensure that packages build correctly with both the `cabal-install` and `stack`
build tools.  If you know that nobody will ever build your project using
`cabal-install` (such as in a closed source project) then you can safely specify
dependencies only at the project-level using `stack` and omit the version
bounds from the `build-depends` section of your `*.cabal` file.

Stackage encompasses a very wide swath of the most heavily used packages in the
Haskell ecosystem, so usually the `resolver` field suffices to lock in the
versions of all packages in your project's dependency graph.  For example, at
the time of this writing 96 of the top 100 packages and 752 of the top 1000
packages (by download) are on Stackage.  You can find the set of packages
constrained by a resolver by visiting:

```
https://www.stackage.org/:resolver/cabal.config
```

For example, you can find the set of package versions constrained by the above
`lts-3.1` resolver here:

[https://www.stackage.org/lts-3.1/cabal.config](https://www.stackage.org/lts-3.1/cabal.config)

Notice that the default `stack.yaml` includes the current directory (i.e. `.`)
as a source dependency of the project.  This reflects the convention that a
`stack.yaml` file is usually located within the source root for your project's
top-level package.

You can also have a "headless" `stack`-managed project with no source
dependencies at all (i.e. the `packages` field is empty), and that's actually a
useful thing to do!  In fact, this Haskell plugin takes advantage of this
feature to do things like opening up a REPL for 3rdparty package.

Here's an example of a more complicated `stack.yaml` file:

```
flags: {}
packages:
- '../foo/bar'
- https://github.com/k0001/pipes-network/archive/pipes-network-0.6.4.tar.gz
extra-deps: [discrimination-0.1, promises-0.2]
resolver: lts-3.1
```

This project specifies the versions of two dependencies not constrained by the
`lts-3.1` Stackage snapshot (specifically the `discrimination` and `promises`
packages).  Additionally, this project has two source dependencies:

* A local package located at the relative directory `../foo/bar`
* A remote source tarball for the `pipes-network` package

The combination of the `resolver`, `extra-deps`, and `packages` fields ensure
that every `stack`-maintained project gives a reproducible build.

### Package caches

Haskell programmers do not distribute packages as precompiled binaries (with the
exception of operating system package distributions like Debian).  Source
packages are the default.

However, that doesn't mean that you always have to recompile every dependency
every time that you build a new project.  `stack` keeps a global package cache
shared by all projects in the user's home directory (somewhere underneath the
`~/.stack` directory).  This prevents wasteful rebuilds of the same dependency
for multiple projects.

To a first approximation this cache stores a precompiled binary for every
unique combination of package name and version number that you depend on.  If
multiple `stack`-managed projects share the same the same "resolver" then
they will make excellent use of the cache because they will all use the same
version of every package that Stackage tracks.

## Implementation

### Targets

The most non-trivial design decision for this plugin is the choice of how to
encode Haskell targets.

For example, when I compile/test/benchmark something am I operating on:

* a Haskell source file?
* a Haskell package?
* a Haskell project?

For the following pants goals the Haskell tool chain only provides support at
the package or project level:

* `test`
* `bench`
* `doc`

For the remaining goals you can provide a reasonable behavior at all three
levels (including the source file level):

* `compile`
* `binary`
* `run`
* `repl`

So you could imagine that we could either have:

* source-file-level `pants` targets,
* package-level `pants` targets, or:
* project-level `pants` targets.

A "source-file-level" target would translate into `ghc` compiler flags used to
build that file.  A "package-level" target would map onto an auto-generated
`*.cabal` file.  A "project-level" target would map onto an auto-generated
`stack.yaml` file.

The first draft of this plugin only provides targets for **projects**, meaning
that these targets will translate into `stack.yaml` files.  The main reason for
this is that there are a few important features that the existing Haskell build
tooling only provides at the project level:

* Dependencies on source packages
* Compiler toolchain bootstrapping and isolation
* `ghc-pkg` package database isolation (really technical topic, not discussed)

These features could be implemented at the package level or source file level,
but they would have to either (A) be reimplemented within `pants` or more likely
(B) simulated by wrapping them in a disposable projects.  I chose to use
project-level targets to get something viable off the ground with as little code
as possible and reusing as much existing Haskell tooling and development idioms
as possible.

Each of the Haskell target types maps 1-to-1 on a field of the `stack.yaml`
file:

* `stackage` target maps onto the `resolver` field for Stackage packages
* `hackage` target maps onto the `extra-deps` field for Hackage packages
* the `cabal` target maps onto the `packages` field for source packages

All three of these targets contain:

* a target `name`
* the package `name`
* a Stackage `resolver` (see the Resolvers section below for more discussion)
* an optional `dependencies` field

For the `stackage` target, that's the only information you need since the
`resolver` already locks in a specific version.

For the `hackage` target, you must also specify a package version.

For the `cabal` target you specify a path to the source distribution which
can be a local directory or a remote tarball.

`stackage` targets are not (yet) necessary as dependencies since they are
already implicitly specified by the resolver field.  Right now the only reason
to have a `stackage` target is if you want to directly `bench`/`test`/`repl` a
3rdparty package.  Later when we add support for generating `*.cabal` files then
these dependencies will be used to complete the `build-depends` section of the
package.

The next logical progression for this plugin would be to add support for
package-level targets so that you could replace `*.cabal` files with `pants`
`BUILD` targets.

### Paths and working directories

This plugin configures the `stack` BUILD tool to use temporary directories
managed by `pants`, with one major exception: the cache directory, which is
located under the user's home directory.  `stack` currently does not let you
configure the cache directory in another location.  If this is an issue I can
open up an issue against the `stack` tool to add support for configuring the
location of the package cache.

`stack` also stores a package-local cache for every source package.  This is how
`stack` implements incremental builds for projects spanning multiple source
packages.  As far as I know the location of these cache directories is also not
configurable and I can similarly open an issue about this if necessary.

### Resolvers

There are two ways you could implement resolvers:

* Every target specifies a `resolver` and tasks verify that all targets in a
  graph share the same `resolver`
* The resolver is specified for the repository as a whole (i.e. in `pants.ini`)

The current implementation uses the former approach.  I made an attempt to use
the latter approach, but then discovered that repository-level flags are just
special cases of optional flags, but it doesn't make sense to make the resolver
optional and `pants` forbids required flags.

### Bootstrapping `stack`

The plugin currently does not bootstrap `stack` yet and instead uses whatever
`stack` it finds on the current `PATH` (if any).  There is no technical reason
for the absence of bootstrapping, I just haven't implemented this feature yet.

### Goals

The `pants` goals translate cleanly onto `stack` goals.  To a first
approximation, `stack` is basically the Haskell version of `pants` and provides
many of the same goals and features (i.e. caching, source dependencies, and
toolchain bootstrapping), which is why the translation between `stack` and
`pants` is straightforward.

If you're familiar with `pants` then you can easily pick up `stack` by just
performing the following translations:

```
./pants compile  ->  stack build
./pants repl     ->  stack ghci
./pants doc      ->  stack haddock
./pants binary   ->  stack install
./pants run      ->  stack run
./pants test     ->  stack test
./pants bench    ->  stack bench
```

## Example Usage

Here are a few example workflows in order of increasing complexity to walk
through what will happen when users run various commands.

### Stackage packages

Let's say that I want to benchmark the `pipes` package on Stackage.  I would
create the following `BUILD` file:

```python
stackage(
  name='pipes',
  package='pipes',
  resolver='lts-3.1',
)
```

... then run:

```shell
$ ./pants bench path/to/build/file:pipes
```

That will then:

* Check to see what `ghc` compiler version is associated with the `lts-3.1`
  resolver (7.10.1 in this case)
* Check to see if the `ghc-7.10.1` compiler toolchain is already installed
* If not installed, then bootstrap and isolate the `ghc-7.10.1` compiler
  toolchain somewhere underneath the `~/.stack` directory
* Learn that version of `pipes` is fixed to `4.1.6` for the `lts-3.1` resolver
* Look up the metadata for the `pipes-4.1.6` package on Hackage to discover its
  immediate dependencies and fix their versions using the resolver
* Continue to transitively fill out the entire dependency graph for `pipes`
* Install all packages in the dependency graph of `pipes` (in parallel when
  possible)
* Cache the built packages somewhere underneath the `~/.stack` directory
* Run the benchmark suite for `pipes`

Note that `pipes` depends on other packages but we do not need to specify them
as `BUILD` target dependencies of our `pipes` target because the resolver
already fixes those dependencies.  The dependencies of every Stackage package
are also guaranteed to be on Stackage.

### Hackage packages

Let's say that I want to load the `discrimination` library into a Haskell REPL
using the `lts-3.1` resolver.  This resolver is missing the `discrimination`
package and one of its dependencies (`promises`) so we can't build this package
unless we fix the version of both the `promises` and `discrimination` packages.

We will fix the `promises` package to version `0.2` and the `discrimination`
package to version `0.1` by creating the following two BUILD targets:

```python
hackage(
  name='promises',
  package='promises',
  resolver='lts-3.1',
  version='0.2',
)

hackage(
  name='discrimination',
  package='discrimination',
  resolver='lts-3.1',
  version='0.1',
  dependencies=[
    ':promises'
  ]
)
```

Then we would load the `discrimination` library into the REPL using:

```shell
$ ./pants repl path/to/build/file:discrimination
```

That will follow the exact same set of steps as in the previous example, but
would instead load the library into the REPL.

If I were to rerun this command it would reuse the cached library from the
previous run and start up much more quickly.

### Remote source packages

Let's say that I want to run an executable produced by a source project that I
find on Github such as the `stack` tool itself.  The package for the `stack`
executable is actually already on Stackage, but it's hard to find a good example
that isn't already on Stackage so this is a little bit contrived.

The `stack` project has a source distribution tarball located here:

[https://github.com/commercialhaskell/stack/archive/v0.1.3.1.tar.gz](https://github.com/commercialhaskell/stack/archive/v0.1.3.1.tar.gz)

... so I would just create the following BUILD file:

```python
cabal(
  name='stack',
  package='stack',
  resolver='lts-3.1',
  path='https://github.com/commercialhaskell/stack/archive/v0.1.3.1.tar.gz',
)
```

... and then I could run the `stack` executable built from that tarball using:

```
./pants run path/to/build/file:stack --run-stack-run-executable=stack
```

We have to specify the executable we wish to run on the command line because a
Haskell package can produce multiple executables.

That would perform the following sequence of steps:
that it would also:

* download the remote source project to a temporary directory
* resolve and compile dependencies the same way as previous examples
* build the executable
* copy the executable underneath `~/.stack`
* delete the temporary directory without caching any work
* run the executable

Note that the work performed for the remote source package is never cached by
`stack`.  If you want to cache the work then you need to create a local copy of
the source package and then `stack` will cache any work in a hidden
`.stack-work` directory underneath that package.

Note that in the above example `stack` would actually recompile the package
**3 times**.  The reason why is that the `./pants run` command translates into
the three sequential `compile`/`binary`/`run` goals, which in turn translate
into the `stack build`/`stack install`/`stack run` commands.  Really only the
last `stack` command needs to be run (like `pants`, the first two `stack` goals
are implied by the third), but that means that you would download and rebuild
the remote package three times instead of just once (because remote packages are
not cached).  That's why I picked this example since it highlights a
pathological corner case in the current plugin behavior.

### Local source project

A much faster approach would be to keep a local copy of the source instead of
pointing to a remote tarball.  Then I would add the following `BUILD` file
within the root of the `stack` local source package:

```python
cabal(
  name='stack',
  package='stack',
  resolver='lts-3.1',
  path='.',
)
```

... and then run the executable using:

```shell
$ ./pants run path/to/stack/project:stack
```

Now this would cache everything and subsequent `run` commands would go much
more quickly.  To be specific, this would:

* resolve dependencies the same as previous examples
* check if the package has been previously cached locally within a `.stack-work`
  directory
* build the project if there is nothing in the cache
* run all tests

### New local project

Let's say that I want to author a new local source package.  I would need to
create the `*.cabal` for my project myself (the Haskell plugin does not yet
generate this file for you), but then I could add the following `BUILD` file to
my project.

```python
cabal(
  name     = 'mypackage',
  package  = 'mypackage',
  resolver = 'lts-3.1',
)
```

Then I could test my project using:

```shell
$ ./pants test path/to/build/file:mypackage
```

This would then perform the same steps as the previous source package example.

#### Project sharing

Another person within a larger repository might author their own local source
package that depends on my local source package.  To do this, they would do
two things:

* Add the name of my package to the `build-depends` field of their `*.cabal`
  file (this Haskell plugin does not currently do this for you)
* Create the following `BUILD` target inside their package directory:

```python
cabal(
  name     = 'theirpackage',
  package  = 'theirpackage',
  resolver = 'lts-3.1',
  dependencies = [
    'path/to/my/build/file:mypackage',
  ]
)
```

Then when they build their package, the tool would:

* resolve all non-source dependencies in the exact same way as before
* check the `~/.stack-work` directory underneath my package to see if my work
  was cached and still valid
* build my package if there is no valid cached build product for my package
* invalidate their package cache if my package changed
* build their package if there is no valid cached build product for their
  package

As you add more source packages with dependencies between each other the `stack`
tool creates an incremental build tree that stores all necessary information
underneath each source package as a `~/.stack-work` directory.  Whenever any
local source package changes only the reverse dependencies of that package need
to be rebuilt.
