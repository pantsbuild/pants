---
title: "Contentious decisions"
slug: "contentious-decisions"
excerpt: "How we make decisions when consensus cannot be reached"
hidden: false
createdAt: "2021-03-17T04:19:25.352Z"
---
Pants is a friendly community, and we prefer to reach decisions by consensus among Maintainers.

To address cases where consensus cannot be reached even after an extended discussion, Maintainers may use a vote to reach a conclusion.

Before calling a vote, it's very important to attempt to reach consensus without a vote. Because discussion and collaboration help us to understand one another's concerns and weigh them, issues that are potentially contentious generally deserve a thread on [pants-devel@googlegroups.com](mailto:pants-devel@googlegroups.com): if you are unsure of whether an issue is contentious, consider sending the mail anyway.

If it becomes clear that all concerns have been voiced, but that consensus cannot be reached via discussion, a Maintainer may call a vote by creating a new thread on [pants-devel@googlegroups.com](mailto:pants-devel@googlegroups.com) with a subject line of the form `[vote] Should We X for Y?`, and a body that presents a series of the (pre-discussed) numbered choices. The Maintainer should publicize the vote in relevant Slack channels such as `#infra` and `#releases`, and on the [pants-committers@googlegroups.com](mailto:pants-committers@googlegroups.com) list.

Because the topic will already have been extensively discussed, the voting thread should not be used for further discussion: instead, it should be filled with responses containing only a list of the individual's ranked numerical choices (from first choice to last choice in descending order), with no rationale included. Individuals may change their votes by replying again.

When a thread has not received any new responses in three business days, the Maintainer who called the vote should reply to request any final votes within one business day (and restart the three day countdown if any new votes arrive before that period has elapsed). On the other hand, if new information is raised on the discussion (note: not voting) thread during the course of voting, the committer who called the vote might choose to cancel the vote and start a new voting thread based on that new information.

When tallying the votes, only Maintainers' votes will be counted: votes are counted using <https://en.wikipedia.org/wiki/Instant-runoff_voting> (the "last choice" alternative is eliminated round by round until only the target number of choices remains), using a simple majority of the participating (i.e., those who replied to the voting thread) Maintainers' votes. Once the votes have been tallied, the Maintainer should reply to the thread with the conclusion of the vote.

It is our goal, and hope, that this process is used only rarely.
