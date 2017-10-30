JVM Dependency Management
=========================

In general, we recommend the [[3rdparty idiom|pants('src/docs:3rdparty')]]
for organizing dependencies on code from outside the source tree. This document
describes how to make this work for JVM (Java or Scala) code.

Your JVM code can depend on external, third-party libraries. Pants uses
[Ivy](http://ant.apache.org/ivy/) to resolve and retrieve these JAR files.
You should know the ([Maven/Ivy groupId, artifactId, and
version](http://maven.apache.org/guides/mini/guide-central-repository-upload.html))
you want to use.

3rdparty/jvm
------------

If you have a small to medium number of third-party dependencies, you can define
them all in a single `3rdparty/jvm/BUILD` file.  If you have a large number, it
may make sense to organize them in multiple subdirectories, say by category or by publisher.

In the appropriate `BUILD` file, you create a <a pantsref="bdict_jar_library">`jar_library`</a>
referencing the <a pantsref="bdict_jar">`jar`</a>s you want:

!inc[start-at=junit&end-before=scalatest](../../../../../../3rdparty/BUILD)

Here, the <a pantsref="bdict_jar_library">`jar_library`</a>'s name
defines a target address that other build targets can refer to. The
<a pantsref="bdict_jar">`jar`</a>s refer to jars that Ivy can resolve and fetch.


Your Code's BUILD File
----------------------

To set up your code to import the external jar, you add a dependency to
the appropriate Java target[s] in your `BUILD` file and add `import`
statements in your Java code.

For example, your `BUILD` file might have

!inc[start-after=junit_tests&end-before=src/java](../../../../../tests/java/org/pantsbuild/example/hello/greet/BUILD)

And your Java code might have:

    :::java
    import org.junit.Test;

"Round Trip" Dependencies
-------------------------

It is possible for your code to exist as source in the repo but
also be published as a binary to an external repository. If you happen to pull in any
third party artifacts, they may express a dependency on the published
version of the artifact.  This means that the classpath will contain
both the version in the repo compiled from source and an older version
that was previously published.  In this case, you want to be sure that
when pants always prefers the version built from source.

Fortunately, the remedy for this is simple.  If you add a `provides=` parameter
that matches the one used to publish the artifact, pants will always prefer the
local target definition to the published jar if it is in the context:

    :::python
    java_library(name='api',
      sources = globs('*.java'),
      provides = artifact(org='org.archie', name='api', repo=myrepo),
    )

    jar_library(name='bin-dep',
      jars=[
        jar(org='org.archie', name='consumer', rev='1.2.3'),
      ],
      dependencies=[
        # Include the local, source copy of the API to cause it to be used rather than
        # any versioned binary copy that the `consumer` lib might depend on transitively.
        ':api',
      ])

Controlling JAR Dependency Versions
-----------------------------------

**If you notice that one "foreign" dependency pulls in mostly wrong
things,** tell Pants not to pull in its dependencies. In your
`3rdparty/.../BUILD` file, use `jar`'s `intransitive` argument; then
carefully add hand-picked versions:

    :::python
    jar_library(name="retro-naming-factory",
      jars=[
	      jar(org='retro', name='retro-factory', rev='5.0.18', intransitive=True),
      ],
      dependencies=[
        # Don't use retro's expected (old, incompatible) common-logging
        # version, yipe; use the same version we use everywhere else:
        '3rdparty/jvm/common-logging',
      ]
    )

**If you notice a small number of transitive dependencies to exclude**
Rather than mark the `jar` intransitive, you can `exclude` some
transitive dependencies from JVM targets:

    :::python
    java_library(name = 'loadtest',
      dependencies = [
        '3rdparty/storm:storm',
      ],
      sources = globs('*.java'),
      excludes = [
        exclude('org.sonatype.sisu.inject', 'cglib')
      ]
    )

Managing Transitive Dependencies
-------------------------------

### The Problem

If you have jars that pull in many transitive dependencies, you probably
want to constrain which versions of those transitive dependencies you
pull in. This is valuable for:

  * Security concerns (you may want to avoid artifacts with known
    vulnerabilities, or you may only want to use particular jars which you
    trust).
  * Predictable and consistent behavior across all projects in your
    repository (described below).
  * Caching concerns/build times (described below).

Otherwise, you may have some targets that end up being built with
version `1.2.3` of a transitive dependency, and others that get built with
`4.5.6` of that dependency. Worse, the *same target* might be built with
different versions of a transitive dependency depending on what other
targets happen to be part of the same pants invocation. To illustrate
this, consider the diagram below:

<div>
  <img alt="image" src="images/transitive-dependencies.png" style="display: block; max-height: 25ex; margin-left: auto; margin-right: auto;">
</div>

Assume `foo` and `bar` are binary targets. If you build a binary of `foo`
with `./pants binary foo`, `foo` will be packaged with the `example` jar
in addition to its transitive dependencies, which will be resolved as the
`common` jar, version `1.2.3`.

Likewise, if you run `./pants binary bar`, it will be packaged with `demo`,
and the transitive dependencies of `demo`, which here is simply the `common`
jar version `4.5.6`.

However, if you run `./pants binary foo bar`, ivy will only resolve one
version of `common-1.2.3`, which most likely means that both `foo` and `bar`
will get `common` version `4.5.6` (because it is the more recent version).
This is a problem, because it may be that `common-4.5.6` is not compatible
with `3rdparty:example`, which will _break the `foo` binary at runtime_.

More subtly, if you have many intermediate `java_library` targets between
your `jvm_binaries` and your `jar_library` targets (which is normaly the
case), simply changing which combination of `java_library` targets are in
the same `./pants` invocation may invalidate the cache and force Pants to
recompile them, even if their sources are unchanged. This is because they
may resolve different versions of their transitive jar dependencies than
the previous time they were compiled, which means their classpaths will be
different. Getting a different classpath causes a cache-miss, forcing a
recompile. In general recompiling when the classpath changes is the
correct thing to do, however this means that unstable transitive
dependencies will cause a lot of cache-thrashing. If you have a large
repository with a large amount of code, recompiles get expensive.

### Possible Solutions

There are a few ways to avoid or work around these problems. A simple method
is to use the [strict ivy conflict manager](http://ant.apache.org/ivy/history/2.4.0/settings/conflict-managers.html),
which will cause the jar resolution to fail with an error if it detects two
artifacts with conflicting versions. This has the advantage of forcing a dev
to be aware of (and make a decision about) confliction versions.

You could also disable transitive jar resolution altogether, and explicitly
declare every dependency you need. This ensures that you have total control
over your external dependencies, but can be difficult to maintain.

The third option is using `managed_jar_dependencies`, to pin the versions of
the subset of your transitive dependencies that you care about.

### Managed Jar Dependencies

Maven handles this problem with the `<dependencyManagement>`
<a href="https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html#Dependency_Management">stanza</a>,
and Pants has similar functionality via the `managed_jar_dependencies` target.

You can set up your `3rdparty/BUILD` file like so:

    :::python
    managed_jar_dependencies(name='management',
      artifacts=[
        ':commons-io',
        ':jersey-core',
      ],
    )

    jar_library(name='commons-io',
      jars=[
        jar('commons-io', 'commons-io', '2.5'),
      ],
    )

    jar_library(name='jersey-core',
      jars=[
        jar('com.sun.jersey', 'jersey-core', '1.19.1'),
      ],
    )

And in `pants.ini`, add:

    :::ini
    [jar-dependency-management]
    default_target: 3rdparty:management

This will force all `jar_library` targets in your repository to use the
versions of `commons-io` and `jersey-core` referenced by the `management`
target. When resolving transitive dependencies, Pants will always choose
the versions "pinned" by the managed dependencies target.

If a `jar_library` omits the version for one of its `jar()`s, it will use
the version defined in `managed_jar_dependencies`. If a `jar()` defines a
version that _conflicts_ with the version set in `managed_jar_dependencies`,
an error will be raised and the build will fail (though this behavior can
be modified via the `conflict_strategy` option).

This is a bit verbose, and entails a bit of duplicate code (you have to
mention `jersey-core` 3 times in the above example). You can use the
`managed_jar_libraries` target factory instead to make your `3rdparty/BUILD`
definitions more concise.

This example is equivalent to the one earlier, but using `managed_jar_libraries`
instead:

    :::python
    managed_jar_libraries(name='management',
      artifacts=[
        jar('commons-io', 'commons-io', '2.5'),
        jar('com.sun.jersey', 'jersey-core', '1.19.1'),
      ],
    )

This automatically generates `jar_library` targets for you, and makes a
`managed_jar_dependencies` target to reference them. (Note that you still
need to make the same change to pants.ini).

The generated library targets follow the naming convention
`org.name.classifier.ext`, where `classifier` and `ext` are omitted if they
are the default values.

So in the above example will generate two `jar_library` targets, called
`3rdparty:commons-io.commons-io` and `3rdparty:com.sun.jersey.jersey-core`.

The artifacts list of `managed_jar_libraries` can also accept target
addresses to already-existing `jar_libraries`, just like a normal
`managed_jar_dependences` target. In this case, `managed_jar_libraries`
will just use the referenced target, rather than generating a new one.

With Pants you can create *multiple* `managed_jar_dependencies`.
If you have more than one, for any particular `jar_library`, you can define
which `managed_jar_dependencies` it uses explicitly (rather than using the
default defined in `pants.ini`):

    :::python
    jar_library(name='org.apache.hadoop-alternate',
      jars=[
        jar('org.apache.hadoop', 'hadoop-common', '2.7.0'),
      ],
      managed_dependencies='3rdparty:management-alternate',
    )

<a pantsmark="test_3rdparty_jvm_snapshot"> </a>

Using a SNAPSHOT JVM Dependency
-------------------------------

Sometimes your code depends on a buggy external JVM dependency. You
think you've fixed the external code, but want to test locally before
uploading it to make sure. To do this, in the `jar` dependency for the
artifact, specify the `url` attribute to point to the local file and
change the `rev`. If you are actively making changes to the dependency,
you can also use the `mutable` jar attribute to re-import the file each
time pants is run (otherwise, pants will cache it):

    :::python
    jar_library(name='checkstyle',
      jars = [
        jar(org='com.puppycrawl.tools', name='checkstyle', rev='5.5-SNAPSHOT',
            url='file:///Users/pantsdev/Src/checkstyle/checkstyle.jar',
            mutable=True),
      ],
    )

Strict Dependencies
-------------------

### What is strict_deps?

Strict_deps is a feature of JVM targets which controls the dependencies
available on the compile classpath when that target is being compiled.

When compiling a JVM target with strict_deps disabled, all transitive
dependencies of that target are included on the compile classpath.

When compiling a JVM target with strict deps enabled, the compile classpath
is more restricted. Instead of containing all transitive dependencies, only
the direct dependencies and the targets exported by those dependencies are
included in the compile classpath.

Enabling strict_deps speeds up builds because it 1) reduces the work the
compiler has to do when searching for symbols, and 2) improves cache hit
rates by reducing the number of dependencies that contribute to a target's
cache keys. This works because most targets don't need their full transitive
dependencies available to compile. However, it does require you to be more
exact in writing down your dependencies.

### Why strict_deps?

Depending on the shape of your build graph, use of strict_deps improves cache
hit rates and per-target compilation time (on the order of 10-20%).

### Example

With strict_deps enabled, we can identified some gaps between what the
compiler expects on a classpath and what is actually available on the
classpath as specified in BUILD files.

Let's look at a simple example involving 3 targets A, B and C. B depends on A,
and C depends on B. Thus their dependency graph can be represented like this:
C->B->A. Their declarations in BUILD file are shown as below:

    :::python
    scala_library(
        name='A',
        source=['A.scala'],
    )

    scala_library(
        name='B',
        source=['B.scala'],
        dependencies=[':A'],
    )

    scala_library(
        name='C',
        source=['C.scala'],
        dependencies=[':B'],
    )

If we compile C with strict_deps turned off, everything works fine, as all
transitive dependencies of C will be added to compile time classpaths.
However, the compilation may require additional dependencies if strict_deps
is turned on. With strict_deps=True, only B is in C's compile time classpath.
There are 2 cases for the failure.

1. C directly uses APIs from A. This is obviously a mistake by author of C,
and the fix is simple, just add A to C's dependency list.

2. C does not use APIs from A, but compiler still wants A to be in C's
classpaths. This is tricky, as author of C may not even be aware of A. It's
hard for C's author to get the right dependency list in this case.

People may wonder why the compiler asks for A to compile C in the first place.
There are a number of reasons for this, an example of which is that the java
compiler needs all transitively implemented interfaces to be on the classpath
so that it can resolve default method implementations.

### Strict_deps for Library Developers

The compile overhead of a library change for downstream targets when
strict_deps is enabled should be minimized to just the targets that
depend directly on the library target or depend on a target that exports
that target.

#### Invalidation

This is a change from the current behavior where all downstream targets will
have their compile invalidated.

With strict_deps, a change to a library target will only invalidate the
compile artifacts of dependent targets if they have

1. A direct dependency on the changed library target, or
2. A dependency on it via the export graph.

Before, if a target depending on a library had an implicit dependency on a
transitive dependency of the library target it would just work. The transitive
dependency would end up on the dependent target’s compile classpath and that
target would compile happily. Strict deps removes that implicit transitivity,
which exposes undeclared dependencies.

This introduces two new sources of errors.

1. When adding a new library dependency to a target, if the library dependency
requires some of its dependencies to be on the compile classpath, the compile
can fail if those dependencies don’t make it on the classpath. These errors
are a bit weird and will be confusing at first.
2. When a library target adds a new publicly visible dependency, targets that
depend on the library target will fail to compile with the same kind of error
message as 1.

### Errors, Exports, and Missing-deps-suggest

The errors sometimes have different messages, but usually in Scala they look
something like this:

    :::bash
    [error] <path-to-current-sources>/<Some-file>.scala:71:32: Symbol 'type
            <Some-type>' is missing from the classpath.
    [error] This symbol is required by '<Some-other-type>.timeout'.
    [error] Make sure that type <Some-type>is in your classpath and check for
            conflicting dependencies with `-Ylog-classpath`.
    [error] A full rebuild may help if <Some-other-type>.class was compiled
            against an incompatible version of <none>.<Some-type>.
    [error]         Some-file.code
    [error]

**NOTE: It's likely the source snippet may not be related to the error**

There are two possible solutions for this error. One is to identify the
dependency that is missing and add it to your target directly.

#### Missing-deps-suggest

Missing-deps-suggest is a feature that will try to identify the target that
failed to compile and suggest a dependency that may be missing.

If this doesn't provide a solution, then the second solution to this error
is exporting the missing type's target in the dependency you depend on.

#### Exports

A target should export any dependencies which provide types or symbols that
are exposed in its public API. For instance, if target A has a method returning
something of type X, it should export the target which defines the type X.

Exports are transitive. This means that if a target exports one of its
dependencies and that exported dependency has exports, those exports will
also be end up on the classpath. This allows the export graph to model
requirements created by type hierarchies.

#### How to Solve An Error With Exports

Let's look at an example failure:

    :::bash
    [1/1] Compiling 1 zinc source in 1 target (examples/src/scala/org/pantsbuild/example/strictdeps:h).
    17:12:58 00:03    [compile]

    17:12:58 00:03      [zinc]
                         [error] Symbol 'type z.Z' is missing from the classpath.
                         [error] This symbol is required by 'method z.X.yyy'.
                         [error] Make sure that type Z is in your classpath and
                                 check for conflicting dependencies with `-Ylog-classpath`.
                         [error] A full rebuild may help if 'X.class' was compiled
                                 against an incompatible version of z.
                         [error] one error found
                         [error] Compile failed at Sep 19, 2017 5:12:59 PM [0.916s]

    17:12:59 00:04      [missing-deps-suggest]

                     compile(examples/src/scala/org/pantsbuild/example/strictdeps:h) failed: Zinc compile failed.
    FAILURE: Compilation failure: Failed jobs: compile(examples/src/scala/org/pantsbuild/example/strictdeps:h)

There are three targets that need to be identified to fix an error like this:

1. the target that failed to compile.
2. the dependency of 1 that owns the type that needed the missing type
3. the dependency of target 2 that owns the missing type.

Target 1 should be the most straight-forward to find. It's the target named in
the failure message as a failed job. It's mentioned both at the end of the
failing compile, in the line starting with `FAILURE: Compilation failure`,
and in a line near the error message. In this example, the failure is
`compile(examples/src/scala/org/pantsbuild/example/strictdeps:h)`. So, target
1 is `examples/src/scala/org/pantsbuild/example/strictdeps:h`.

Finding target 2 involves looking at target 1's dependencies and figuring out
which one contains the type from the error message. First, let's find the
type. In a message like this, target 2's type is the one that required the
missing type. In this message specifically, it's the following line:

    :::bash
    [error] This symbol is required by 'method z.X.yyy'.

The type from target 2 is the method `yyy` on `z.X`. How to we find
the target for that type? One way would be to eyeball it. Let's look at the
BUILD file.

    :::python
    scala_library(
        name='h',
        sources=['H.scala'],
        dependencies=[':x'],
        strict_deps=True
    )

In this example, target 1 only has one dependency, `x`. That makes finding
target 2 easy. It's `:x`.

Now that we know target 1 and target 2, let's find 3. Since we're doing this
manually, we'll look at the build files again.

Here's target 2's BUILD file declaration:

    :::python
    scala_library(
        name='x',
        sources=['X.scala'],
        dependencies=[':z']
    )

It too has only one dependency, so we know what Target 3 is. It's `:z`.

Now that we know what the missing dependency is, we can fix the error.
Z has to be on the classpath in order to use X, so any target depending
on `:x` will also need `:z`. We could just add a dependency on :z to :h, but
doing so would result in new users of `:x` running into this same error. To
prevent that, let's add an export to `:x` of `:z`.

    :::python
    scala_library(
        name='x',
        sources=['X.scala'],
        dependencies=[':z'],
        exports=[':z']
    )

Now our target compiles successfully.
