####################
Publishing Artifacts
####################

A library owner/maintainer can *publish* versioned artifacts that
folks elsewhere can fetch and import. In the JVM world, these are jars
(with poms)
on a server that Maven (or Ivy) looks for. (In the Python world, these are
eggs; but as of late 2013, Pants doesn't help publish these.)

.. WARNING::
   This page describes ``pants goal publish``. Alas, this goal is not, in fact,
   built into Pants *yet*. If you work in an organization with a Pants guru,
   you might have a ``publish`` goal. Otherwise, please consider this a sneak
   preview of an upcoming feature.

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

  It's usually a sign that something strange happened in a *previous* publish.
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

* Pushing the pushdb to origin can fail, even though artifact-uploading succeeded. Perhaps you
  were publishing at about the same time someone else was; you might get a
  merge conflict when trying to push.

  (There's a temptation to ignore this error: the artifact uploaded OK; nobody
  expects a merge conflict when publishing. Alas, ignoring the error now means
  that your *next* publish will probably fail, since Pants has lost track of
  the current version number.)

  :ref:`Troubleshoot a Failed Push to Origin <publish-pushdb-push>`

******
How To
******

* Does your organization enforce a special branch for publishing? (E.g., perhaps
  publishing is only allowed on the ``master`` branch.) If so, be on that branch
  with no changes.

* Consider trying a local publish first. This lets you test the to-be-published
  artifact. E.g., to test with Maven configured to use ``~/.m2/repository``
  as a local repo, you could publish to that repo with
  ``./pants goal publish --no-publish-dryrun --publish-local=~/.m2/repository``

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

***************
Troubleshooting
***************

Sometimes publishing doesn't do what you want. The fix usually involves
publishing again, perhaps passing ``--publish-override``,
``--publish-force``, and/or ``--publish-restart-at``. The following
are some usual symptoms/questions:

.. _publish-version-exists:

Versioned Artifact Already Exists
=================================

Pants attempted to compute the new version number to use based on the
contents of the pushdb; but apparently, someone previously published
that version of the artifact without updating the pushdb.

Examine the publish repo to find out what version number you actually
want to use.

Try publishing again, but pass ``--publish-override`` to specify the
version number to use instead of incrementing the version number from
the pushdb.

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

The exact steps to fix things up depend on what was happening on your
local repo. Some good things to consider.

  * Update your source tree, discarding local changes.
    In git, this might be a ``reset origin/master``
    (if ``master`` is your release branch) and a ``pull``.
  * Look at the pushdb's source control history to if someone made a conflicting
    publish. If so, contact them.
    (You're about to try to publish again; if they also encountered
    problems, they are probably also about to try again. You might want to
    coordinate and take turns.)
  * Try publishing again.
    Since you uploaded new versions artifacts but the pushdb doesn't "remember"
    that, you might run into errors with this publish, as ivy hits
    Versioned Artifact Already Exists.
    Use ``--publish_override`` to set version numbers for these.

.. _publish-no-provides:

Does not provide an artifact
============================

Pants gets the coordinates at which to publish a target from the target's
``provides`` parameter. Thus, if you try to publish a target with no
``provides``, Pants doesn't know what to do. It stops::

  FAILURE: The following errors must be resolved to publish.
    Cannot publish src/java/com/twitter/common/base/BUILD:base due to:
      src/java/com/twitter/common/quantity/BUILD:quantity - Does not provide an artifact.

The solution is to add a ``provides`` to the target that lacks one.

Remember, to publish a target, the target's dependencies must also be published.
If any of those dependencies have changed since their last publish, Pants
tries to publish them before publishing the target you specify. Thus, you
might need to add a ``provides`` to one or more of these.

