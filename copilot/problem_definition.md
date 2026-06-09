## Problem definition

The e8b784f897c4658a365becbc669c384240573b5e commit adds support for uv lockfiles as an alternative
to pex lockfiles.

However, the implementation of uv support has a known capability regression vs. pex for cold-cache
builds: the pex resolver subsets the lockfile per target; the uv resolver always materializes the
full resolve first. For ML-heavy users with large 3rdparty deps, this can lead to out-of-disk issues
on CI agents when building even small PEX files with only a few dependencies.

Read the Slack conversation in copilot/slack.md for more details on the issue and potential
workarounds.

Analyze the code changes in the commit and propose a solution to address this capability regression
in uv support.
Evaluate the feasibility of the proposed solution in the last message - it involves using uv's
`--only-group` option and generating an ephemeral dependency group for just the immediate
dependencies needed for the PEX build. Consider the implementation complexity, potential edge cases,
and how it would integrate with the existing Pants build system.
