class CherryPickHelper {
  constructor({ octokit, context, core }) {
    this.octokit = octokit;
    this.context = context;
    this.core = core;
  }

  get #issue_context() {
    const pull_number =
      this.context.issue.number ||
      core.getInput("inputName", { required: true });
    return {
      ...this.context.repo,
      // NB: In GitHub nomenclature, pull requests are (also) issues.
      issue_number: pull_number,
      pull_number,
    };
  }

  get #run_link() {
    return `:robot: [Beep Boop here's my run link](${this.context.serverUrl}/${this.context.repo.owner}/${this.context.repo.repo}/actions/runs/${this.context.runId}/jobs/${this.context.job})`;
  }

  #get_branch_name(milestone_title) {
    return `cherry-pick-${
      this.#issue_context.pull_number
    }-to-${milestone_title}`;
  }

  async #add_failed_label() {
    await this.octokit.rest.issues.addLabels({
      ...this.#issue_context,
      labels: ["auto-cherry-picking-failed"],
    });
  }

  async #add_comment(body) {
    await this.octokit.rest.issues.createComment({
      ...this.#issue_context,
      body,
    });
  }

  async #get_relevant_milestones(milestone_title) {
    const semver = require("semver");
    const { data: all_milestones } =
      await this.octokit.rest.issues.listMilestones({
        ...this.#issue_context,
        state: "open",
      });
    const sorted_milestones = all_milestones
      .map((milestone) => milestone.title)
      .filter((title) => title.startsWith("2.") && title.endsWith(".x"))
      .sort((a, b) => semver.compare(semver.coerce(a), semver.coerce(b)));
    const relevant_milestones = sorted_milestones.slice(
      sorted_milestones.indexOf(milestone_title)
    );
    return relevant_milestones;
  }

  async get_prereqs() {
    const { data: pull } = await this.octokit.rest.pulls.get({
      ...this.#issue_context,
    });

    if (pull.milestone == null) {
      const { data: workflows } =
        // NB: GitHub doesn't give you the URL to the workflow, or the filename, when running a workflow.
        await this.octokit.rest.actions.listRepoWorkflows({
          ...this.#issue_context,
        });
      const workflow_url = workflows.filter(
        (workflow) => workflow.name === this.context.workflow
      )[0].url;

      await this.#add_failed_label();
      await this.#add_comment(
        `I was unable to cherry-pick this PR; the milestone seems to be missing.

Please add the milestone to the PR and re-run the [Auto Cherry-Picker job](${workflow_url}) using the "Run workflow" button.

${this.#run_link}`
      );
      this.core.setFailed(`PR missing milestone.`);
      return null;
    }

    const milestones = await this.#get_relevant_milestones(
      pull.milestone.title
    );
    return {
      pr_num: this.#issue_context.pull_number,
      merge_commit: pull.merge_commit_sha,
      milestones: milestones,
    };
  }

  async cherry_pick_failed(merge_commit_sha, milestone_title) {
    this.#add_failed_label();
    await this.#add_comment(
      `I was unable to cherry-pick this PR to ${milestone_title}, likely due to merge-conflicts.

To resolve:
1. (Ensure your git working directory is clean)
2. Run the following script to reproduce the merge-conflicts:
    \`\`\`bash
    git checkout https://github.com/pantsbuild/pants main \\
      && git pull \\
      && git fetch https://github.com/pantsbuild/pants ${milestone_title} \\
      && git checkout -b ${this.#get_branch_name(milestone_title)} FETCH_HEAD \\
      && git cherry-pick ${merge_commit_sha}
    \`\`\`
3. Fix the merge conflicts, commit the changes, and push the branch to a remote
4. Run \`pants run build-support/bin/cherry_pick/make_pr.js -- --pull-number="${
        this.#issue_context.pull_number
      }" --milestone="${milestone_title}"\`

${this.#run_link}`
    );
  }

  async cherry_pick_succeeded(milestone_titles) {
    // NB: Unfortunately, we can't have the cherry-pick job use outputs to send the PR numbers, since
    //  it uses a matrix and currently GitHub doesn't support matrix job outputs well
    //  (See https://github.com/orgs/community/discussions/26639#discussioncomment-3252675).
    const pr_urls = await Promise.all(
      milestone_titles.map(async (milestone_title) => {
        return this.octokit.rest.pulls.list({
          ...this.#issue_context,
          state: "open",
          head: this.#get_branch_name(milestone_title),
        });
      })
    ).then((all_pulls) =>
      all_pulls.map(({ data: pulls }) => pulls[0].html_url)
    );

    let prs_list = "";
    for (let i = 0; i < pr_urls.length; i++) {
      prs_list += `- Cherry-pick to ${milestone_titles[i]}: ${pr_urls[i]}\n`;
    }

    await this.#add_comment(
      `I was successfully able to open the following PRs:
${prs_list}
Please note that I cannot re-kick CI if a job fails. Please work with your PR approver(s) to re-kick CI if necessary.

Thanks again for your contributions!

${this.#run_link}`
    );
    await this.octokit.rest.issues.removeLabel({
      ...this.#issue_context,
      name: "needs-cherrypick",
    });
  }
}

module.exports = CherryPickHelper;
