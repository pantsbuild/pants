########################
Pants Contributors Guide
########################

This page documents how to make contributions to Pants. If you've
:doc:`developed a change to Pants <howto_develop>`, it passes all
tests (current test status: |travis-bot|), and you'd like to "send
it upstream", here's what to do:

.. TODO: Document the release process.
.. TODO: Coding Conventions section

.. |travis-bot| image:: https://travis-ci.org/twitter/commons.png?branch=master
                :target: https://travis-ci.org/twitter/commons

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

Overall its quite straightforward. Please note - despite being hosted on
GitHub - we do not use pull requests because we prefer a linear commit history
and doing code reviews with Review Board.


Getting Pants Source Code
=========================

After deciding on the change you'd like to make we'll need to get the code. ::

   git clone https://github.com/twitter/commons

After getting the code, you may want to familiarize yourself with the
:doc:`internals` or :doc:`howto_develop`. We'll create a new branch off master
and make our changes. ::

   git checkout -b $FEATURE_BRANCH


Code Review
===========

Now that your change is complete, we'll post it for review. The first time
posting a review you'll need to:

* Create an account at https://rbcommons.com
* Install `RBTools <http://www.reviewboard.org/docs/rbtools/dev/>`_ to
  simplify interacting with Review Board.

Post your change for review. ::

   rbt post

This will create a new review, but not yet publish it. At the provided URL you
need to fill in the change description, reviewers, testing done, etc. When the
review looks good publish it. An email will be sent to `pants-devel` mailing
list and the reviewers will take a look. If they have any feedback there might
be a few iterations before finally getting a Ship It.


Commit Your Change
==================

At this point you've made a change, had it reviewed and are ready to
complete things by getting your change in master. If you're not a committer
please ask one do do this section for you. ::

   cd /path/to/pants/repo
   git checkout master
   git pull
   git merge --squash $FEATURE_BRANCH
   git push origin master

The very last step is closing the review. The change is now complete. Huzzah!
