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
clone url of your fork and your github username. Then run the following commands:

    :::bash
    $ git remote add <your-username> <url-to-clone-your-fork>

After this change, `git push <your-username>` and `git pull <your-username>` will
go to your fork. You can get the latest changes from the `pantsbuild/pants` repo's
master branch using the [syncing a fork](https://help.github.com/articles/syncing-a-fork/)
instructions on github.

Whether you've cloned the repo or your fork of the repo, you should setup the
local pre-commit hooks to ensure your commits meet minimum compliance checks
before pushing branches to ci:

    :::bash
    $ ./build-support/bin/setup.sh

You can always run the pre-commit checks manually via:

    :::bash
    $ ./build-support/bin/pre-commit.sh

**Pro tip:** If you are certain that you have not accidentally committed anything to
the `master` branch that you want to keep, and you want to reset to an _exact_ copy of
the `pantsbuild/pants` repo's master branch, use these commands:

    :::bash
    $ git co master
    $ git fetch origin
    $ git reset --hard origin/master

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

Now that your change is complete, post it for review. We use `github.com` pull requests
to host code reviews:

#### Posting the First Draft

When <a pantsref="dev_run_all_tests">all of the tests are green on travis</a>, you're
probably ready to request review for the change! 

To get your pull request reviewed, you should fill in:

- A useful change description, with a short and descriptive title.
- Any specific [pants committers](https://github.com/orgs/pantsbuild/teams/committers)
  who should review your change to the Assignees field. Running `git log -- $filename` on
  one or more of the files that you changed is a good way to find potential reviewers!

Finally, when the review is ready for attention, add the `reviewable` label: this is the
signal to committers and contributors that the review is ready for attention. You can see
a list of all actively `reviewable` reviews [here](https://github.com/pantsbuild/pants/labels/reviewable).

Note that while only committers are available to add in the Assignees field,
any pants contributors may still post reviews if you provide them with a link
manually or they see it in the google group or github notifications.

#### Iterating

If reviewers post any feedback
([for more information on providing feedback see](https://help.github.com/articles/reviewing-proposed-changes-in-a-pull-request/)),
there might be a few iterations before finally getting a Ship It. As reviewers enter
feedback, the github page updates; it should also send
you mail as long as you are `Subscribed` to notifications for the pull request.

If those reviews inspire you to change some code, great. Change some
code and commit locally. When you're ready to update the pull request with your changes,
push to the relevant branch on your fork as you did before:

    :::bash
    $ git push <your-username> $FEATURE_BRANCH

Look over the fields in the pull request you created earlier; perhaps some could use updating.
Press the web form's `edit` button.
    
If at any point you need to make changes that will fundamentally overhaul a review,
consider temporarily removing the `reviewable` label in order to let reviewers know
to hold off until the code is ready.

### Commit Your Change

At this point you've made a change, had it reviewed (and received one or more Ship Its!) and
are ready to complete things by getting your change in master. (If you're not a
committer, please ask one to do this section for you.)

A committer should push the `Squash and merge` button on the PR, and ensure that the
commit message generated from the review summary is accurate. In particular, the title should
contain a useful summary of the change, and the description should fully describe the change
and its implications for users.

Finally, the committer will select `Confirm squash and merge`. The change is now complete. Huzzah!
