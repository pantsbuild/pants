####################
JVM 3rdparty Pattern
####################

In general, we use :doc:`the 3rdparty idiom <3rdparty>` to organize
dependencies on code from outside the source tree. This document
describes how to make this work for JVM (Java or Scala) code.

Your JVM code can pull in code written elsewhere.
Pants uses `Ivy <http://ant.apache.org/ivy/>`_, a tool based on Maven's
jar-sharing. You should know the
(`Maven/Ivy groupId, artifactId, and version <http://maven.apache.org/guides/mini/guide-central-repository-upload.html>`_)
you want to use.

The 3rdparty pattern described here eases avoiding diamond dependency
problems and version conflicts. If your code depends on artifacts
``foo`` and ``bar``; and if ``foo`` and ``bar`` depend on different versions
of the ``baz`` artifact; then some code will be linked together with a
version of ``baz`` it didn't "expect." Tracking versioned
dependencies in one place makes it easier to reason about them.

************
3rdparty/jvm
************

**The JVM part of 3rdparty is organized by org (Maven groupId)** Under there,
see if there's already a ``3rdparty/jvm/path/to/org/BUILD`` file.
If there isn't, then you want to create one. E.g., to import
``com.sun.jersey-apache-client``, look in ``3rdparty/jvm/com/sun``
for a likely-looking ``BUILD`` file--in this example,
``3rdparty/jvm/com/google/sun/jersey/BUILD``.

In the appropriate ``BUILD`` file, you want to find a
:ref:`bdict_jar_library` with the :ref:`bdict_jar`\s you want:

.. literalinclude:: ../../../../3rdparty/BUILD
   :start-after: Test support
   :end-before: specs


Here, the
:ref:`bdict_jar_library`\s's name defines a target address that other build
targets can refer to. The :ref:`bdict_jar`\s refer to jars known
to your Ivy resolver.

If there's already a ``jar`` importing the code you want but with a
*different* version, then you probably want to talk to other folks in your
organization to agree on one version. (If there's already a ``jar`` importing
the code you want with the version you want, then great. Leave it there.)

(You don't *need* a tree of ``BUILD`` files; you could instead have, e.g., one
``3rdparty/jvm/BUILD`` file. In a large organization, a tree can ease some
things. For example, ``git log`` quickly answers questions like "Who set up
this dependency? Who cares if I bump the version?")

Additionally, some families of jars have different groupId's but are logically
part of the same project, or need to have their rev's kept in sync. For example,
(``com.fasterxml.jackson.core``, ``com.fasterxml.jackson.dataformat``).
Sometimes it makes sense to define these in a single build file,
such as ``3rdparty/jvm/com/fasterxml/jackson/BUILD`` for the jackson family of jars.

**********************
Your Code's BUILD File
**********************

To set up your code to import the external jar, you add a
dependency to the appropriate Java target[s] in your ``BUILD`` file
and add ``import`` statements in your Java code.

For example, your ``BUILD`` file might have

.. literalinclude:: ../../../../tests/java/com/pants/examples/hello/greet/BUILD
   :start-after: sources
   :end-before: src/java

And your Java code might have::

    import org.junit.Test;

*************************
"Round Trip" Dependencies
*************************

Depending on your workspace's relation with the rest of the world, you might
want to look out for "round trip" dependencies.
You can publish an artifact *near* generated from your workspace's source code
and consume a third-party artifact *far* that depends on *near*.
If you're not careful, you might depend on two versions of the *near* code:
the local source code and an artifact you published a while ago.
When consuming such third-party artifacts, exclude dependencies that
"collide" with source code and depend on local source::

    jar_library(name='far',
      jars=[
        # exclude conflicting dep:
        jar(org='org.archie', name='far', rev='0.0.18').with_sources()
          .exclude(org='org.archimedes', name='near')
      ]
      dependencies=[
        # and re-include local version of source manually:
        pants('util/near'),
      ]
    )

******************************************
Troubleshooting a JVM Dependencies Problem
******************************************

If you're working in JVM (Java or Scala) and suspect you're pulling in
different versions of some package, you can dump your dependency "tree"
with versions with an Ivy resolve report. To generate a report for
a target such as the ``hello/main`` example::

    $ ./pants goal resolve src/java/com/pants/examples/hello/main --ivy-open

Ivy's report shows which things depend on which versions. You can see which
package is pulling in the package-version you didn't expect. (It might not
be clear which version you want to use; but at least you'll know what's
causing the problem.)

**If you notice a small number of wrong-version things,** then in a JVM
target, you can depend on a ``jar`` that specifies a version and
sets ``force=True`` to *force* using that version::

  scala_library(
    name = "loadtest",
    dependencies = [
      pants('3rdparty/bijection:bijection-scrooge'),
      # our 3rdparty/BUILD still has 6.1.4 as the default version, but
      # finagle-[core|thrift] version 6.1.4 is superceded (evicted) by
      # version 6.4.1
      # Force inclusion of version 6.1.4, until we're bumped to finagle 6.4.1+
      jar(org='com.twitter', name='iago', rev='0.6.3', force=True),
      jar(org='com.twitter', name='finagle-core', rev='6.1.4', force=True),
      jar(org='com.twitter', name='finagle-thrift', rev='6.1.4', force=True),
    ],
    sources = ["LoadTestRecordProcessor.scala"])

**If you notice that one "foreign" dependency pulls in mostly wrong things,**
tell Pants not to pull in its dependencies. In your ``3rdparty/.../BUILD``
file, call the ``jar``\'s ``intransitive`` method; then carefully add
hand-picked versions::

    jar_library(name="retro-naming-factory",
      jars=[
        jar(org='retro', name='retro-factory', rev='5.0.18').intransitive(),
      ],
      dependencies=[
        # Don't use retro's expected (old, incompatible) common-logging
        # version, yipe; use the same version we use everywhere else:
	pants('3rdparty/jvm/common-logging'),
      ])

**If you notice a small number of transitive dependencies to exclude**
Rather than mark the ``jar`` intransitive, you can ``exclude`` some
transitive dependencies from JVM targets::

    java_library(name = 'loadtest',
      dependencies = [
        pants('3rdparty/storm:storm'),
      ],
      sources = globs('*.java'),
      excludes = [
        exclude('org.sonatype.sisu.inject', 'cglib')
      ]
    )

**If you notice a missing dependency**, check for a naming conflict. When bringing in multiple jars
with the same org, name, and version, only the first reference will win, and subsequent references
will be silently discarded. One way that this can occur is with dependencies that use a classifier
to differentiate themselves. Consider this example::

    jar_library(name = 'stanford-corenlp',
      jars = [
        jar(org = 'edu.stanford.nlp', name = 'stanford-corenlp', rev = '3.3.1').with_sources(),
        jar(org = 'edu.stanford.nlp', name = 'stanford-corenlp', rev = '3.3.1', classifier='models')
      ]
    )

In the above example, the ``edu.stanford.nlp.stanford-corenlp-3.3.1-models.jar`` will be silently
skipped by pants. To bring both jars in, use the ``.with_artifacts()`` method of the
:ref:`bdict_jar`. Using this method, the above example would be transformed into::

    jar_library(name = 'stanford-corenlp',
      jars = [
        jar(org = 'edu.stanford.nlp', name = 'stanford-corenlp', rev = '3.3.1').with_sources().with_artifact(classifier='models').with_artifact(classifier=''),
      ]
    )

And as a result, both jars will now be brought into the target's classpath.

