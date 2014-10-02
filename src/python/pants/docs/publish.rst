####################
Publishing Artifacts
####################

A library owner/maintainer can *publish* versioned artifacts that
folks elsewhere can fetch and import. In the JVM world, these are jars
(with poms)
on a server that Maven (or Ivy) looks for. (In the Python world, these are
eggs; but as of early 2014, Pants doesn't help publish these.)

This page talks about publishing artifacts. We assume you already know enough
about Pants to *build* the library that underlies an artifact.
To *use* an artifact that has already been published from some other
source tree, see :doc:`3rdparty`. (To use a artifact that has been
published from *your own* source tree... don't do that. Instead, depend on
the ``*_library`` build target.)

It's tricky to keep track of versions, label artifacts with versions, and
upload those artifacts. Pants eases these tasks.

A library's build target specifies where to publish it.
For example, a :ref:`bdict_java_library` build target can have a ``provides``
parameter of type :ref:`bdict_artifact`. The ``artifact`` specifies an
"address" similar to what you might see in ``3rdparty`` ``BUILD`` files:
an artifact's location. It does *not* specify a version; that changes
each time you publish.

Pants' ``publish`` goal builds the library, bumps the library's version
number, and uploads the library to its repository. Actually, it does
quite a bit more than that.

It uses `Semantic Versioning ("semver") <http://semver.org/>`_ for versioning.
Versions are dotted number triads (e.g., 2.5.6); when Pants bumps a version,
it specifically bumps the patch number part. Thus, if the current version is
2.5.6, Pants bumps to 2.5.7. To publish a minor or major version instead of
a patch, you override the version number on the command line.

**The pushdb:** To "remember" version numbers, Pants uses the pushdb.
The pushdb is a text file under source control. It lists artifacts with
their current version numbers and SHAs. When you publish artifacts,
pants edits this file and pushes it to the origin.

*****************
Life of a Publish
*****************

To publish a library's artifact, Pants bumps the version number and uploads
the artifact to a repository. When things go smoothly, that's all
you need to know. When things go wrong, it's good to know details.

* Pants decides the version number to use based on pushdb's state.

  You can override the version number[s] to use via a command-line flag.
  Pants does some sanity-checking: If you specify an override version less
  than or equal to the last-published version (as noted in the pushdb),
  Pants balks.

* For each artifact to be published, it prompts you for confirmation.
  (This is a chance for you to notice that you want to, e.g.,
  bump an artifact's minor revision instead of patch revision.)

* Invokes a tool to upload the artifact to a repository.
  (For JVM artifacts, this tool is Ivy.)

* Commits pushdb.

Things can go wrong; you can recover:

* Uploading the artifact can fail for reasons you might expect for an upload:
  authentication problems, transient connection problems, etc.

* Uploading the artifact can fail for another reason: that artifact+version
  already exists on the server. *In theory*, this shouldn't happen: Pants
  bumps the version it found in the pushdb. But in practice, this can happen. ::

    Exception in thread "main" java.io.IOException: destination file exists and overwrite == false
    ...
    FAILURE: java -jar .../ivy/lib/ivy-2.2.0.jar ... exited non-zero (1) 'failed to push com.twitter#archimedes_common;0.0.42'

  This is usually a sign that something strange happened in a *previous*
  publish.
  Perhaps someone published an artifact "by hand" instead of using Pants.
  Perhaps someone used Pants to publish an artifact but it failed to update
  the pushdb in source control. E.g., merge conflicts can happen, and folks
  don't always recover from them correctly.

  In this situation, you probably want to pass ``--publish-override`` to
  specify a version to use instead of the automatically-computed
  already-existing version. Choose a version that's not already on the server.
  Pants records this version in the pushdb, so hopefully the next
  publisher won't have the same problem.

  Perhaps you are "racing" a colleague and just lost the race:
  they published an artifact with that name+version.

  In this situation, you probably want to refresh your source tree
  (``git pull`` or equivalent) to get the latest version of the pushdb
  and try again.

* Pushing the pushdb to origin can fail, even though artifact-uploading succeeded.
  Perhaps you
  were publishing at about the same time someone else was; you might get a
  merge conflict when trying to push.

  (There's a temptation to ignore this error: the artifact uploaded OK; nobody
  expects a git merge conflict when publishing.
  Alas, ignoring the error now means
  that your *next* publish will probably fail, since Pants has lost track of
  the current version number.)

  See: :ref:`Troubleshoot a Failed Push to Origin <publish-pushdb-push>`

******
How To
******

* Does your organization enforce a special branch for publishing? (E.g., perhaps
  publishing is only allowed on the ``master`` branch.) If so, be on that branch
  with no changes.

* Consider trying a local publish first. This lets you test the to-be-published
  artifact. See :ref:`publish_local_test`.

* Start the publish: ``./pants goal publish --no-publish-dryrun [target]``
  Don't wander off; Pants will ask for confirmation as it goes
  (making sure you aren't publishing artifact[s] you didn't mean to).

*******************************
Restricting to "Release Branch"
*******************************

Your organization might have a notion of a special "release branch": you want
all publishing to happen on this source control branch, which you maintain
extra-carefully. You can
:ref:`configure your repo <setup_publish_restrict_branch>`
so the ``publish`` goal only allows ``publish``-ing from this special branch.

*****************************************
Authenticating to the Artifact Repository
*****************************************

Your artifact repository probably doesn't accept anonymous uploads; you probably
need to authenticate (prove that you are really you). Depending on how
the artifact repository set up, Pants might need to interact the authentication
system. (Or it might not. E.g., if your system uses Kerberos, when Pants invokes
artifact-upload commands, Kerberos tickets should work automatically.)

If Pants needs to provide your username and password, you can enable this
via Pants' ``.netrc`` support. Pants can parse
`.netrc files
<http://www.gnu.org/software/inetutils/manual/html_node/The-_002enetrc-File.html>`_
to get a user's username and password on an artifact repository machine.
To make this work:

* Each user needs a ``~/.netrc`` file with a section that looks like ::

    machine our-artifacts.archimedes.org
      login sandy
      password myamazingpa$sword

* One of your top-level ``BUILD`` files needs a target that represents
  ``netrc`` auth::

    netrc = netrc()

    credentials(
      name = 'netrc',
      username=netrc.getusername,
      password=netrc.getpassword)

* Your ``pants.ini`` file's ``'auth'`` section for that repository should
  refer to that target::

    [jar-publish]
    workdir: %(pants_workdir)s/publish
    repos: {
        'external': {
          'resolver': 'art.archimedes.org',
          'confs': ['default', 'sources', 'docs', 'changelog'],
          'auth': 'BUILD.archimedes:netrc',
          'help': 'Configure your ~/.netrc for artifact repo access!'
        },
    }

If you need to implement some other kind of authentication,
you might look at `the Netrc implementation
<https://github.com/pantsbuild/pants/blob/master/src/python/pants/authentication/netrc_util.py>`_
and the :ref:`bdict_credentials` target type for inspiration.

***************
Troubleshooting
***************

Sometimes publishing doesn't do what you want. The fix usually involves
publishing again, perhaps passing
``--publish-override`` (override the version number to use),
``--publish-force``, and/or ``--publish-restart-at``. The following
are some usual symptoms/questions:

.. _publish-version-exists:

Versioned Artifact Already Exists
=================================

Pants attempted to compute the new version number to use based on the
contents of the pushdb; but apparently, someone previously published
that version of the artifact without updating the pushdb.

Examine the publish repo to find out what version number you actually
want to use. E.g., if you notice that versions up to 2.5.7 exist and
you want to bump the patch version, you want to override the default
version number and use 2.5.8 instead.

Try publishing again, but pass ``--publish-override`` to specify the
version number to use instead of incrementing the version number from
the pushdb. Be sure to use a version number that has not
already been published this time. For example, to override the default
publish version number for the ``org.archie`` buoyancy artifact, you might
pass ``--publish-override=org.archie#buoyancy=2.5.8``.

.. _publish-pushdb-push:

Failed to Push to Origin
========================

You might successfully publish your artifact but then fail to push
your pushdb change to origin::

    To https://git.archimedes.org/owls
     ! [rejected]        master -> master (non-fast-forward)
    error: failed to push some refs to 'https://git.archimedes.org/owls'
    hint: Updates were rejected because the tip of your current branch is behind
    hint: its remote counterpart. Merge the remote changes (e.g. 'git pull')
    hint: before pushing again.
    hint: See the 'Note about fast-forwards' in 'git push --help' for details.

For some reason, git couldn't merge your branch (with the pushdb change)
to the branch on origin.
This might happen, for example, if you were "racing" someone else; they
perhaps pushed their change to master's pushdb before you could.
But it can also happen for other reasons; any local change that can't
be merged to the branch on origin.

You are now in a bad state: you've pushed some artifacts, but the pushdb
doesn't "remember" them.

* Look at the pushdb's source control history to if someone made a conflicting
  publish. If so, contact them.
  (You're about to try to fix the problem; if they also encountered
  problems, they are probably also about to fix the problem.
  You might want to coordinate and take turns.)

* Git couldn't auto-merge your change to the pushdb; can you fix the merge
  "by hand"? If the problem is just a merge conflict in the pushdb, you can
  fix things by fixing the merge. (But if someone else was trying to publish
  a particular artifact at the same time you were, your changes may be too
  "entangled" to salvage this way.)

**To reset and start over** In git, this might mean::

    git reset origin/master # (if ``master`` is your release branch)
    git pull
    ./pants goal clean-all && ./pants goal publish <your previous args>

Since you uploaded new versioned artifacts but the reset pushdb doesn't
"remember" that, you might get "Versioned Artifact Already Exists"
errors: see the section above, and use ``--publish-override`` to set
version numbers to avoid these.

.. _publish-no-provides:

Does not provide an artifact
============================

A published artifact lives at a set of coordinates. For Pants to publish an
artifact, it needs to know the artifact's coordinates.
Pants gets the coordinates from the target's
``provides`` parameter. Thus, if you try to publish a target
that depends on a target
that has no ``provides``,
Pants doesn't know what to do. It stops::

  FAILURE: The following errors must be resolved to publish.
    Cannot publish src/java/com/twitter/common/base/BUILD:base due to:
      src/java/com/twitter/common/quantity/BUILD:quantity - Does not provide an artifact.

The solution is to add a ``provides`` to the target that lacks one.

Remember, to publish a target, the target's dependencies must also be published.
If any of those dependencies have changed since their last publish, Pants
tries to publish them before publishing the target you specify. Thus, you
might need to add a ``provides`` to one or more of these.

Silently does not publish
=========================

A published artifact lives at a set of coordinates. For Pants to publish an
artifact, it needs to know the artifact's coordinates.
Pants gets the coordinates from the target's
``provides`` parameter. Thus, if you try to publish a target
that has no ``provides``,
Pants doesn't try. If the target depends on *other*
targets that *do* provide artifacts, Pants might publish those.
This is a case of :ref:`goal-target mismatch <tut_goal_target_mismatch>`.
To fix this, set ``provides`` correctly.

**********************************************
Want to Publish Something? Publish Many Things
**********************************************

If you publish a library that depends on others, you want to
publish them together.
Conversely, if you publish a low-level library that other libraries depend upon,
you want to publish those together, too.
Thus, if you want to publish one thing, you may find you should publish
many things.
Pants eases *part* of this: if you publish a library, it automatically
prompts you to also publish depended-upon libraries whose source code changed.
However, Pants does *not*
automatically publish dependees of a depended-upon library.
If you know you're about to publish a low-level library
(perhaps via a "dry run" publish),
you can use Pants' ``goal dependees`` to find other things to publish.

For example, suppose your new library ``high-level`` depends on another
library, ``util``.
If you tested ``high-level`` with ``util`` version 1.2, you want ``util``
1.2 published and available to ``high-level`` consumers.
Once you publish ``util`` version 1.2, people might use it.
If you previously published your ``another-high-level`` library
library depending on ``util`` version 1.1, ``another-high-level`` consumers
(who might also consume ``high-level``) might pick up version 1.2 and be sad
to find out that ``other-high-level`` doesn't work with the new ``util``.

In this example, when you publish ``high-level``, Pants knows to also publish
``util``.
If Pants publishes ``util``, it does *not* automatically try to publish
``high-level`` or ``other-high-level``.

.. _publish_local_test:

********************************
Test with a Fake Local "Publish"
********************************

The whole reason you publish an artifact so that other codebases can use it.
Before you really publish, you might want to fake-publish an artifact:
generate it and put it someplace a place in your development machine;
then use that artifact from another codebase.

For example, your other codebase might use
Maven to build, perhaps with Maven configured to use ``~/.m2/repository``
as a local repo.
You can make pants publish to that local repo with ::

    ./pants goal publish --no-publish-dryrun --publish-local=~/.m2/repository

In the other codebase, change the dependencies to pull in the new artifact.

If your other codebase *also* uses Pants build, you can depend on the
locally-published artifact. If the artifact is a jar, then in the
3rdparty
:ref:`jar target <bdict_jar>`,
set ``mutable=True`` and change the version number.

*************************************************
Appendix A: Adding extra artifacts to the publish
*************************************************

.. TODO(lahosken) make this section its own page.
   Remember link to it from this page and from dev_task
   and to fix up the link from the sample code

Pants supports "publish plugins", which allow end-users to add additional,
arbitrary files to be published along with the primary artifact. For example,
let's say that along with publishing your jar full of class files, you would
also like to publish a companion file that contains some metadata -- code
coverage info, source git repository, java version that created the jar, etc.
To accomplish this, you'll first need to write a custom task, which creates any
additional files (jar or otherwise) that you would like to publish. Next,
you'll create a ``publish_extras`` section under ``[jar-publish]`` in
pants.ini, and add a key for the new product type. Your custom task will create
the extra file(s) that you want to publish, and write the path to the products
map under the key that you have defined in pants.ini. The publishing code will
loop over all keys found in pants.ini, and consult the product map. If pants
finds a file for the current key, it will gather it up, and bundle it in with
the rest of the files being published.

An example of a custom task is supplied in the
``examples/src/python/example/pants_publish_plugin`` directory. To use it, add
the following to your pants.ini::

    [jar-publish]
    publish_extras: {
        'extra_test_jar_example': {
          'override_name': '{target_provides_name}-extra_example',
          'classifier': 'classy',
          'extension': 'jar',
        },
      }

    [backends]
    packages: [
        'example.pants_publish_plugin',
      ]

In the above configuration example, the string 'extra_test_jar_example' is a
key into the product map. In this case, the example task will add additional
files for publishing to the product map under this key. And ``jar_publish.py``
will examine the product map, looking for all keys defined here, and publishing
any additional files found.

Constructing a name for your extra artifact:
============================================
By default, pants uses the following scheme when publishing artifacts::

    [artifactId]-[version](-[classifier]).[ext]

The pants plugin publishing system allows a customization of the artifact
identifier, classifier, and file extension. To customize the name of your extra
object, you can supply some extra parameters in the ``pants.ini`` file:

 * ``override_name`` -- allows customization of the name (``artifactId``) of
   the additional file published. Specifying a string will completely override
   the name, or include '``{target_provides_name}``' to tack an addition on to
   the pre-existing artifact name. Defaults to the pre-existing artifact name.

 * ``classifier`` -- the maven classifier. Can be any arbitrary string, or
   leave this unspecified for nothing.

 * ``extension`` -- the filename extension. Defaults to "jar".

**Note:** You must supply a non-default value for at least one of the above
parameters, otherwise your extra publish artifact won't have a unique name.
With the above config in your pants.ini, invoke pants like this, to do a test
publish::

    WRAPPER_SRCPATH=examples/src/python PANTS_DEV=1 ./pants goal publish examples/src/java/com/pants/examples/hello/greet --no-publish-dryrun --publish-local=~/tmp

Now if you examine the ``/tmp`` directory, you'll notice that an extra jar has
been published for the ``greet`` target::

    $ ls -1 /tmp/com/pants/examples/hello-greet/0.0.1-SNAPSHOT/|grep example
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar.md5
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar.sha1

This example task should provide a rough starting guide, and can be tailored to
suit a more specific situation.
