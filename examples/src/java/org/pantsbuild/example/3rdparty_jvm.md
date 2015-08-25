JVM 3rdparty Pattern
====================

In general, we use the
[[3rdparty idiom|pants('src/docs:3rdparty')]] to organize
dependencies on code from outside the source tree. This document
describes how to make this work for JVM (Java or Scala) code.

Your JVM code can pull in code written elsewhere. Pants uses
[Ivy](http://ant.apache.org/ivy/), a tool based on Maven's jar-sharing.
You should know the ([Maven/Ivy groupId, artifactId, and
version](http://maven.apache.org/guides/mini/guide-central-repository-upload.html))
you want to use.

The 3rdparty pattern described here eases avoiding diamond dependency
problems and version conflicts. If your code depends on artifacts `foo`
and `bar`; and if `foo` and `bar` depend on different versions of the
`baz` artifact; then some code will be linked together with a version of
`baz` it didn't "expect." Tracking versioned dependencies in one place
makes it easier to reason about them.

3rdparty/jvm
------------

**The JVM part of 3rdparty is organized by org (Maven groupId).**
For an example of a repo with 3rdparty arranged this way, see
[twitter/commons](https://github.com/twitter/commons/tree/master/3rdparty/jvm).
(Pants' own 3rdparty isn't organized this way; it doesn't have enough 3rdparty
dependencies for this to make sense.)
Under there, see if there's already a `3rdparty/jvm/path/to/org/BUILD` file.
If there isn't, then you want to create one. E.g., to import
`com.sun.jersey-apache-client`, look in `3rdparty/jvm/com/sun` for a
likely-looking `BUILD` file--in this example,
`3rdparty/jvm/com/google/sun/jersey/BUILD`.

In the appropriate `BUILD` file, you want to find a
<a pantsref="bdict_jar_library">`jar_library`</a>
with the <a pantsref="bdict_jar">`jar`</a>s you want:

!inc[start-at=junit&end-before=scalatest](../../../../../../3rdparty/BUILD)

Here, the
<a pantsref="bdict_jar_library">`jar_library`</a>'s name
defines a target address that
other build targets can refer to. The
<a pantsref="bdict_jar">`jar`</a>s refer to jars known to
your Ivy resolver.

If there's already a `jar` importing the code you want but with a
*different* version, then you probably want to talk to other folks in
your organization to agree on one version. (If there's already a `jar`
importing the code you want with the version you want, then great. Leave
it there.)

(You don't *need* a tree of `BUILD` files; you could instead have, e.g., one `3rdparty/jvm/BUILD`
file. Pants' own repo has its JVM 3rdparty targets in just one `BUILD` file. That works fine because
Pants doesn't have many 3rdparty JVM dependencies. But as the number of these dependencies grows,
it makes more sense to set up a directory tree. In a large organization, a tree can ease some
common tasks. For example, `git log` quickly answers questions like "Who set up this dependency?
Who cares if I bump the version?")

Additionally, some families of jars have different groupId's but are
logically part of the same project, or need to have their rev's kept in
sync. For example, (`com.fasterxml.jackson.core`,
`com.fasterxml.jackson.dataformat`). Sometimes it makes sense to define
these in a single build file, such as
`3rdparty/jvm/com/fasterxml/jackson/BUILD` for the jackson family of
jars.

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

Depending on your workspace's relation with the rest of the world, you
might want to look out for "round trip" dependencies. You can publish an
artifact *near* generated from your workspace's source code and consume
a third-party artifact *far* that depends on *near*. If you're not
careful, you might depend on two versions of the *near* code: the local
source code and an artifact you published a while ago.

When consuming such third-party artifacts, ensure that your source dependencies
have `provides` clauses (*near*), and then add the source dependencies
explicitly when you depend on the binary copy of the *far* dependency:

    :::python
    jar_library(name='far',
      jars=[
        jar(org='org.archie', name='far', rev='0.0.18'),
      ]
      dependencies=[
        # including the local version of source manually will cause the binary
        # dependency to be automatically excluded:
        'util/near',
      ]
    )

Troubleshooting a JVM Dependencies Problem
------------------------------------------

If you're working in JVM (Java or Scala) and suspect you're pulling in different versions of some
package, you can dump your dependency "tree" with versions with an Ivy resolve report.
To generate a report for a target such as the `junit`-using `hello/greet` example tests:

    :::bash
    $ ./pants resolve.ivy --open examples/tests/java/org/pantsbuild/example/hello/greet

Ivy's report shows which which package is pulling in the package-version you didn't expect.
(It might not be clear which version you *want*; but at least you've narrowed down the problem.)

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
