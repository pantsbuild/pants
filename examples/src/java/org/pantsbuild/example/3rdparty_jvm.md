JVM 3rdparty Pattern
====================

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

!inc[start-after=sources&end-before=src/java](../../../../../tests/java/org/pantsbuild/example/hello/greet/BUILD)

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

Fortunately, the remedy for this is simple.  If you add a `provides=`
parameter that matches the one used to publish the artifact, pants
will always prefer the local target definition to the
published jar.

    :::python
    jar_library(name='api',
      sources = globs('*.java'),
      provides = artifact(org='org.archie',
                          name='api',
                          repo=myrepo,)
	)

Controlling JAR Dependency Versions
-----------------------------------

**If you notice a small number of wrong-version things,** then in a JVM
target, you can depend on a `jar` that specifies a version and sets
`force=True` to *force* using that version:

    :::python
    scala_library(
      name = "loadtest",
      dependencies = [
        '3rdparty/bijection:bijection-scrooge',
        # our 3rdparty/BUILD still has 6.1.4 as the default version, but
        # finagle-[core|thrift] version 6.1.4 is superceded (evicted) by
        # version 6.4.1
        # Force inclusion of version 6.1.4, until we're bumped to finagle 6.4.1+
        jar(org='com.twitter', name='iago', rev='0.6.3', force=True),
        jar(org='com.twitter', name='finagle-core', rev='6.1.4', force=True),
        jar(org='com.twitter', name='finagle-thrift', rev='6.1.4', force=True),
      ],
      sources = ["LoadTestRecordProcessor.scala"])

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
      ])

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
