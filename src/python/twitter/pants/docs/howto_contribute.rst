########################
Pants Contributors Guide
########################

This page documents how to make contributions to Pants. If you've
:doc:`developed a change to Pants <howto_develop>`, it passes all
tests, and you'd like to "send
it upstream", here's what to do:

.. TODO: Document the release process.
.. TODO: Coding Conventions section

************
Mailing List
************

Join the `pants-devel Google Group
<https://groups.google.com/forum/#!forum/pants-devel>`_
to keep in touch with other pants developers.


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

   git clone https://github.com/twitter/commons

After getting the code, you may want to familiarize yourself with the
:doc:`internals` or :doc:`howto_develop`. We'll create a new branch off master
and make our changes. ::

   git checkout -b $FEATURE_BRANCH

Run the CI Tests
================

Before posting a review but certainly before the branch ships you should run
relevant tests. If you're not sure what those are you can always run the
same test set-up that's run on `Travis CI
<https://travis-ci.org/twitter/commons/>`_.

To run the full jvm and python suite including a pants self-rebuild. ::

   ./build-support/bin/ci.sh

You can also skip certain steps including pants bootstrapping. Just use the
``-h`` argument to get command line help on the options available.


Code Review
===========

Now that your change is complete, we'll post it for review.
We use https://rbcommons.com to host code reviews and
`rbt <http://www.reviewboard.org/docs/rbtools/dev/>`_ (RBTools)

Posting the First Draft
-----------------------

**Before posting your first review,** you must create an
account at https://rbcommons.com . To create one, visit
https://rbcommons.com/account/login/ and click "Create one now."

To set up local tools, run `./rbt status`.
(``./rbt`` is a wrapper around the usual RBTools ``rbt`` script.)
The first time this runs it will bootstrap and you will be asked to log in.
Subsequent runs use your cached login credentials.

Post your change for review::

   ./rbt post -o -g

This will create a new review, but not yet publish it.

At the provided URL, there's a web form. To get your change reviewed,
you must fill in the change description, reviewers, testing done, etc.
To make sure it gets seen, add ``pants-reviews`` to the Groups field.
When the review looks good, publish it.
An email will be sent to ``pants-devel`` mailing list and the reviewers
will take a look. (For your first review, double-check that the mail got sent;
rbcommons tries to "spoof" mail from you and it doesn't work for everybody's
email address.)

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
please ask one do do this section for you.) ::

   cd /path/to/pants/repo
   ./build-support/bin/ci.sh
   git checkout master
   git pull
   git merge --squash $FEATURE_BRANCH
   git commit -a

Here, fix up the commit message: replace ``git``'s default message
("Squashed commit of the following... <long list>") with a summary.
Finally, ::

   git push origin master

The very last step is closing the review. The change is now complete. Huzzah!

**If you're a committer committing someone else's review,** a handy way to
patch a local branch with a diff from rbcommons where
<RB_ID> is a review number like 123::

   ./rbt patch -c <RB_ID>
