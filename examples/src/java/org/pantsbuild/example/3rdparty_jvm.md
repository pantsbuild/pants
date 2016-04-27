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
