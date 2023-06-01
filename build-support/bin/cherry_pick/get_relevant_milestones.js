module.exports = async ({ github, context, core }) => {
  const semver = require("semver");

  const { data: all_milestones } = await github.rest.issues.listMilestones({
    ...context.repo,
    state: "open",
  });
  const sorted_milestones = all_milestones
    .map((milestone) => milestone.title)
    .sort((a, b) => semver.compare(semver.coerce(a), semver.coerce(b)));

  const pr_num = "${{ github.event.pull_request.number || inputs.PR_number }}";
  const { data: pull } = await github.rest.pulls.get({
    ...context.repo,
    pull_number: pr_num,
  });

  if (pull.milestone == null) {
    this.octokit.rest.issues.createComment({
      ...this.issue_context,
      // @TODO: URL to Job
      body: `I couldn't find a milestone on this PR. Please add the relevant milestone and re-run ...`,
    });
    core.setFailed(`Couldn't find any relevant milestones.`);
  }

  const target_milestone = pull.milestone.title;

  const milestone_index = sorted_milestones.indexOf(target_milestone);
  if (milestone_index < 0) {
    this.octokit.rest.issues.createComment({
      ...this.issue_context,
      body: `I was unable to find any relevant milestones to cherry-pick to.`,
    });
    core.setFailed(`Couldn't find any relevant milestones.`);
  }

  const relevant_milestones = sorted_milestones.slice(milestone_index);

  core.setOutput("pr_num", pr_num);
  core.setOutput("merge_commit", pull.merge_commit_sha);
  core.setOutput("milestones", relevant_milestones);
};
