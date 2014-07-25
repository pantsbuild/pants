########################
Pants Contributors Guide
########################

This page documents how to make contributions to Pants. If you've
:doc:`developed a change to Pants <howto_develop>`, it passes all
tests, and you'd like to "send
it upstream", here's what to do:

.. TODO: Document the release process.
.. TODO: Coding Conventions section

******************************
Questions, Issues, Bug Reports
******************************

See :doc:`howto_ask`

*********************
Join the Conversation
*********************

Join the `pants-devel Google Group
<https://groups.google.com/forum/#!forum/pants-devel>`_
to keep in touch with other pants developers.

Join the `pants-reviews Google Group
<https://groups.google.com/forum/#!forum/pants-reviews>`_
to see many code reviews.

Watch the `pantsbuild/pants Github project
<https://github.com/pantsbuild/pants>`_ for
notifications of new issues, etc.

Follow `@pantsbuild on Twitter <https://twitter.com/pantsbuild>`_
for occasional announcements.

Find out when the CI tests go red/green by adding your email address to
`.travis.yml <https://github.com/pantsbuild/pants/blob/master/.travis.yml>`_.

****************
Life of a Change
****************

Let's walk through the process of making a change to pants. At a high level
we'll do the following:

* Identify the change you'd like to make (e.g.: fix a bug, add a feature).
* Get the code.
* Make your change on a branch.
* Get a code review.
* Commit your change to master.

Overall it's quite straightforward. Please note - despite being hosted on
GitHub - we do not use pull requests because we prefer a linear commit history
and doing code reviews with Review Board.


Identify the change
===================

It's a good idea to make sure the work you'll be embarking on is generally
agreed to be in a useful direction for the project before getting too far
along.

If there is a pre-existing github issue filed and un-assigned, feel free to
grab it and ask any clarifying questions needed on `pants-devel
<https://groups.google.com/forum/#!forum/pants-devel>`_. If there is an issue
you'd like to work on that's assigned and stagnant, please ping the assignee
and finally `pants-devel
<https://groups.google.com/forum/#!forum/pants-devel>`_ before taking over
ownership for the issue.

If you have an idea for new work that's not yet been discussed on `pants-devel
<https://groups.google.com/forum/#!forum/pants-devel>`_, then start a
conversation there to vet the proposal. Once the group agrees it's worth
a spike you can file a github issue and assign it to yourself.


Getting Pants Source Code
=========================

After deciding on the change you'd like to make we'll need to get the code. ::

   git clone https://github.com/pantsbuild/pants

After getting the code, you may want to familiarize yourself with the
:doc:`internals` or :doc:`howto_develop`. We'll create a new branch off master
and make our changes. ::

   git checkout -b $FEATURE_BRANCH

Run the CI Tests
================

Before posting a review but certainly before the branch ships you should run
relevant tests. If you're not sure what those are,
:ref:`run all the tests <dev_run_all_tests>`.

Code Review
===========

Now that your change is complete, we'll post it for review.
We use https://rbcommons.com to host code reviews.

Posting the First Draft
-----------------------

**Before posting your first review,** you must create an
account at https://rbcommons.com . To create one, visit
https://rbcommons.com/account/login/ and click "Create one now."

To set up local tools, run ``./rbt help``.
(``./rbt`` is a wrapper around the usual RBTools
`rbt <http://www.reviewboard.org/docs/rbtools/dev/>`_ script.)
The first time this runs it will bootstrap: you'll see a lot
of building info.

Post your change for review::

   ./rbt post -o -g

The first time you ``post``, rbt asks you to log in.
Subsequent runs use your cached login credentials.

This ``post`` creates a new review, but does not yet publish it.

At the provided URL, there's a web form. To get your change reviewed,
you must fill in the change description, reviewers, testing done, etc.
To make sure it gets seen, add ``pants-reviews`` to the Groups field
and a specific reviewer to the People field.

When the review looks good, publish it.
An email will be sent to the ``pants-reviews`` mailing list and the reviewers
will take a look. (For your first review, double-check that the mail got sent;
rbcommons tries to "spoof" mail from you and it doesn't work for everybody's
email address. If your address doesn't work, you might want to use another one.)

Iterating
---------

If reviewers have feedback, there might
be a few iterations before finally getting a Ship It.
As reviewers enter feedback, the rbcommons page updates; it should also
send you mail (but sometimes its "spoof" fails).

If those reviews inspire you to change some code, great. Change some code,
commit locally. To update the code review with the new diff where
<RB_ID> is a review number like 123::

    ./rbt post -o -r <RB_ID>

Look over the fields in the web form; perhaps some could use updating.
Press the web form's Publish button.

Commit Your Change
==================

At this point you've made a change, had it reviewed and are ready to
complete things by getting your change in master. (If you're not a committer,
please ask one to do this section for you.) ::

   cd /path/to/pants/repo
   ./build-support/bin/ci.sh
   git checkout master
   git pull
   ./rbt patch -c <RB_ID>

Here, ensure that the commit message generated from the review summary is
accurate, and that the resulting commit contains the changes you expect.
Finally, ::

   git push origin master

The very last step is closing the review as "Submitted". The change is now
complete. Huzzah!
