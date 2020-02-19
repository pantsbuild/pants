Pants Committers
================

The Pants project welcomes contributions from all developers.  In order to properly vet changes to the codebase, we have a review process and your code must be approved and committed to the repo by a developer with commit access to the pantsbuild github project.

A Committer is a member of the community who has access to commit changes to the master branch of the github repo.  We limit the number of committers to developers who have a proven track record with contributing code changes and actively participate in the project through code contributions, reviews, and community discussions.

Becoming a Committer
--------------------

Nominations for committers are discussed on the <pants-committers@googlegroups.com> group.  The discussion will consider commits contributed to date and the participation of the contributor in reviews and public communication channels.  Feedback is gathered on what might be required for the contributor to be approved as a committer.

The minimum requirement to become a committer is evidence of at least 10 "significant contributions" to the open source repo.  The definition of what constitutes a "significant contribution" is kept intentionally vague, but at a minimum, those contributions should:

  - Include changes that impact code, test, and documentation.
  - Be vetted by committers from multiple organizations.
  - Cover more than a single area of the pants codebase.
  - Demonstrate knowledge of and willingness to follow project development processes and procedures.

After approval by a vote of the current committers, a new committer has access to the following resources:

  - Commit access to the github repo.
  - Ability to Stop/restart builds on Travis-CI.
  - Access to the <pants-committers@googlegroups.com> group.

A committer may also request access to publish changes to the org.pantsbuild groupId on the Maven Central Repository.

The list of current and past committers will be listed in a file named COMMITTERS.md in the root of the pantsbuild/pants repo.

Committer Responsibilities
--------------------------

It is the responsibility of a Committer to ensure that the ongoing good health and high quality of the project is maintained.

  - Committers are responsible for the quality of the changes that they approve.
  - Committers should raise objections to changes that may impact the performance, security, or maintainability of the project.
  - Committers should help shepherd changes from non-committers through our contribution process.
  - Committers should maintain a courteous and professional demeanor when participating in the community.
  - Committers should be regular participants on our public communications channels.

Committers should respond to public requests for code reviews.  While it is not necessary for every review to be approved by every committer, the health of the community depends on quality vetting of incoming changes.  If only a single committer is tagged on a review and is unable to participate, the committer should respond to the review and recommend another committer.

Contentious Decisions
---------------------

To help address cases where consensus cannot be reached even after extended discussion, committers
may use a vote to reach a conclusion.

Before calling a vote, it's very important to attempt to reach consensus without a vote. Because
discussion and collaboration help us to understand one another's concerns and weigh them, issues
that are potentially contentious generally deserve a thread on <pants-devel@googlegroups.com>: if
you are unsure of whether an issue is contentious, consider sending the mail anyway.

If it becomes clear that all concerns have been voiced, but that consensus cannot be reached via
discussion, a committer may call a vote by creating a new thread on <pants-devel@googlegroups.com>
with a subject line of the form `[vote] Should We X for Y?`, and a body that presents a series of
the (pre-discussed) numbered choices. The committer should publicize the vote in relevant Slack
channels such as `#infra` and `#releases`, and on the <pants-committers@googlegroups.com> list.

Because the topic will already have been extensively discussed, the voting thread should _not_ be
used for further discussion: instead, it should be filled with responses containing only a list of
the individual's ranked numerical choices (from first choice to last choice in descending order),
with no rationale included. Individuals may change their votes by replying again.

When a thread has not received any new responses in three business days, the committer who called
the vote should reply to request any final votes within one business day (and restart the three day
countdown if any new votes arrive before that period has elapsed). On the other hand, if new
information is raised on the discussion (note: not voting) thread during the course of voting, the
committer who called the vote might choose to cancel the vote and start a new voting thread based on
that new information.

When tallying the votes, only committer's votes will be counted: votes are counted using
<https://en.wikipedia.org/wiki/Instant-runoff_voting> (the "last choice" alternative is eliminated
round by round until only the target number of choices remains), using a simple majority of the
participating (ie, those who replied to the voting thread) committer's votes. Once the votes have
been tallied, the committer should reply to the thread with the conclusion of the vote.

Releaser
--------

A Releaser is a Committer who has permission to publish releases to the pantsbuild.pants PyPI repository.  A Committer who wishes to participate in the pants release rotation may additionally become a Releaser.   A Releaser is responsible for updating the release documentation, creating release builds, and shepherding them through the review and release process.

Committer Emeritus
------------------

A committer may be placed on emeritus status.  This is an honorary position for committers who were formerly active in the community but have retired from active Pants life.  These committers do not have commit access to the repositories.

The decision to place a committer on emeritus status is either by request, or by majority vote of the committers.  If you have not participated in code reviews or contributed a patch to pants within the past three months an automatic recommendation for emeritus status may be put forward to the committers.

