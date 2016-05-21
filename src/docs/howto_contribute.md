Pants Contributors Guide
========================

This page documents how to make contributions to Pants. If you've
[[developed a change to Pants|pants('src/docs:howto_develop')]],
it passes all tests, and
you'd like to "send it upstream", here's what to do:

Questions, Issues, Bug Reports
------------------------------

See [[How To Ask|pants('src/docs:howto_ask')]]

Join the Conversation
---------------------

Join the [pants-devel Google Group][pants-devel] to keep in touch with other
pants developers.

Join the [pantsbuild Slack team](https://pantsbuild.slack.com) and hop on the
`#general` channel for higher bandwidth questions and answers about hacking on
or using pants. You can [send yourself an invite](https://pantsslack.herokuapp.com/) or ask for one
on the [pants-devel Google group][pants-devel].

Watch the [pantsbuild/pants Github
project](https://github.com/pantsbuild/pants) for notifications of new
issues, etc.

Follow [@pantsbuild on Twitter](https://twitter.com/pantsbuild) for
occasional announcements.

Find out when the CI tests go red/green by adding your email address to
[.travis.yml](https://github.com/pantsbuild/pants/blob/master/.travis.yml).

[pants-devel]: https://groups.google.com/forum/#!forum/pants-devel "pants-devel Google Group"

Life of a Change
----------------

Let's walk through the process of making a change to pants. At a high
level, the steps are:

-   Identify the change you'd like to make (e.g.: fix a bug, add a feature).
-   Get the code.
-   Make your change on a branch.
-   Get a code review.
-   Commit your change to master.

Please note--despite being hosted on GitHub--we do not use pull
requests to merge to master; we prefer to maintain a linear commit
history and to do code reviews with Review Board. You will however
need to create a Github pull request in order to kick off CI and test
coverage runs.

### Identify the change

It's a good idea to make sure the work you'll be embarking on is
generally agreed to be in a useful direction for the project before
getting too far along.

If there is a pre-existing github issue filed and un-assigned, feel free
to grab it and ask any clarifying questions needed on
[pants-devel](https://groups.google.com/forum/#!forum/pants-devel). If
there is an issue you'd like to work on that's assigned and stagnant,
please ping the assignee and finally
[pants-devel](https://groups.google.com/forum/#!forum/pants-devel)
before taking over ownership for the issue.

If you have an idea for new work that's not yet been discussed on
[pants-devel](https://groups.google.com/forum/#!forum/pants-devel), then
start a conversation there to vet the proposal. Once the group agrees
it's worth a spike you can file a github issue and assign it to
yourself.

<a pantsmark="download_source_code"></a>

### Getting Pants Source Code

If you just want to compile and look at the source code, the easiest way
is to clone the repo.

    :::bash
    $ git clone https://github.com/pantsbuild/pants

If you would like to start developing patches and contributing them
back, you will want to create a fork of the repo using the [instructions
on github.com](https://help.github.com/articles/fork-a-repo/). With this
setup, you can push branches and run Travis-CI before your change is
committed.

If you've already cloned your repo without forking, you don't have to
re-checkout your repo. First, create the fork on github. Make a note the
clone url of your fork. Then run the following commands:

    :::bash
    $ git remote remove origin
    $ git remote add origin <url-to-clone-your-fork>
    $ git remote add upstream  https://github.com/pantsbuild/pants

After this change, `git push` and `git pull` will go to your fork. You
can get the latest changes from the `pantsbuild/pants` repo's master
branch using the [syncing a
fork](https://help.github.com/articles/syncing-a-fork/) instructions on
github.

Whether you've cloned the repo or your fork of the repo, you should setup the
local pre-commit hooks to ensure your commits meet minimum compliance checks
before pushing branches to ci:

    :::bash
    $ ./build-support/bin/setup.sh

You can always run the pre-commit checks manually via:

    :::bash
    $ ./build-support/bin/pre-commit.sh

**Pro tip:** If you want your local master branch to be an exact copy of
the `pantsbuild/pants` repo's master branch, use these commands:

    :::bash
    $ git co master
    $ git fetch upstream
    $ git reset --hard upstream/master

### Making the Change

You might want to familiarize yourself with the
[[Pants Internals|pants('src/docs:internals')]],
[[Pants Developers Guide|pants('src/docs:howto_develop')]], and the
[[Pants Style Guide|pants('src/docs:styleguide')]].

Create a new branch off master and make changes.

    :::bash
    $ git checkout -b $FEATURE_BRANCH

Does your change alter Pants' behavior in a way users will notice? If
so, then along with changing code...

+   Consider updating the
    [[user documentation|pants('src/docs:docs')]].

### Run the CI Tests

Before posting a review but certainly before the branch ships you should
run relevant tests. If you're not sure what those are,
<a pantsref="dev_run_all_tests">run all the tests</a>.

### Code Review

Now that your change is complete, post it for review. We use `rbcommons.com` to host code reviews:

#### Posting the First Draft

**Before posting your first review,** you need to both subscribe to the [pants-reviews
Google Group](https://groups.google.com/forum/#!forum/pants-reviews) and create an
[RBCommons](https://rbcommons.com) account.  Its critical that the email address you use for each
of these is the same, and it's also recommended that you have that same email address registered as
one of your [email addresses](https://github.com/settings/emails) with Github.

_A special warning to `@twitter.com` contributors:_ The twitter.com email domain does not permit
emails being sent on behalf of its members by RBCommons. As such, you should use a personal email
address or some other non-`@twitter.com` email address to subscribe to both RBCommons and
pants-reviews.

To create your RBCommons account, visit <https://rbcommons.com/account/login/> and click "Create
one now.".  To sign up for pants-reviews@googlegroups.com, just browse to
<https://groups.google.com/forum/#!forum/pants-reviews/join>.

To set up local tools, run `./rbt help`. (`./rbt` is a wrapper around
the usual RBTools [rbt](http://www.reviewboard.org/docs/rbtools/dev/)
script.) The first time this runs it will bootstrap: you'll see a lot of
building info.

Before you post your review to Review Board you should <a
pantsref="dev_run_all_tests">create a Github pull request</a> in order
to kick off a Travis-CI run against your change.

Post your change for review:

    :::bash
    $ ./rbt post -o -g

The first time you `post`, rbt asks you to log in. Subsequent runs use
your cached login credentials.

This `post` creates a new review, but does not yet publish it.

At the provided URL, there's a web form. To get your change reviewed,
you must fill in the change description, reviewers, testing done, etc.
To make sure it gets seen by the appropriate people and that they have
the appropriate context, add:

- `pants-reviews` to the Groups field
- Any specific [pants committers](https://www.rbcommons.com/s/twitter/users/)
  who should review your change to the People field
- The pull request number from your Github pull request in the Bug field
- Your git branch name in the Branch field.

When the review looks good, publish it. An email will be sent to the
`pants-reviews` mailing list and the reviewers will take a look. (For
your first review, double-check that the mail got sent; rbcommons tries
to "spoof" mail from you and it doesn't work for everybody's email
address. If your address doesn't work, you might want to use another
one.)

Note that while only committers are available to add in the People field,
users with an rbcommons account may still post reviews if you provide
them with a link manually or they see it in the google group.

#### Iterating

If reviewers have feedback, there might be a few iterations before
finally getting a Ship It. As reviewers enter feedback, the rbcommons
page updates; it should also send you mail (but sometimes its "spoof"
fails).

If those reviews inspire you to change some code, great. Change some
code, commit locally. To update the code review with the new diff where
`<RB_ID>` is a review number like `123`:

    :::bash
    $ ./rbt post -o -r <RB_ID>

Look over the fields in the web form; perhaps some could use updating.
Press the web form's Publish button.

If need a reminder of your review number, you can get a quick list with:

    :::bash
    $ ./rbt status
    r/1234 - Make pants go even faster

### Commit Your Change

At this point you've made a change, had it reviewed and are ready to
complete things by getting your change in master. (If you're not a
committer, please ask one to do this section for you.)

    :::bash
    $ cd /path/to/pants/repo
    $ ./build-support/bin/ci.sh
    $ git checkout master
    $ git pull
    $ ./rbt patch -c <RB_ID>

Here, ensure that the commit message generated from the review summary
is accurate, and that the resulting commit contains the changes you
expect. (If `rbt` gives mysterious errors, pass `--debug` for more info.
If that doesn't clarify the problem, mail pants-devel (and include that
`--debug` output).)

Finally,

    :::bash
    $ git push origin master

The very last step is closing the review as "Submitted". The change is
now complete. Huzzah!
