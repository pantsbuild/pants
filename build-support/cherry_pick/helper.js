// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
class CherryPickHelper {
  constructor({ octokit, context, core }) {
    this.octokit = octokit;
    this.context = context;
    this.core = core;
    this.pull_number =
      this.context.issue.number || this.context.payload.inputs.PR_number;
  }

  get #issue_context() {
    return {
      ...this.context.repo,
      // NB: In GitHub nomenclature, pull requests are (also) issues.
      issue_number: this.pull_number,
    };
  }

  get #pull_context() {
    return {
      ...this.context.repo,
      pull_number: this.pull_number,
    };
  }

  get #run_link() {
    return `:robot: [Beep Boop here's my run link](${this.context.serverUrl}/${this.context.repo.owner}/${this.context.repo.repo}/actions/runs/${this.context.runId})`;
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
    const index = sorted_milestones.indexOf(milestone_title);
    const relevant_milestones = sorted_milestones.slice(
      index === -1 ? 0 : index
    );
    return relevant_milestones;
  }

  async get_prereqs() {
    const { data: pull } = await this.octokit.rest.pulls.get({
      ...this.#pull_context,
    });

    if (pull.milestone == null) {
      const { data: workflows } =
        // NB: GitHub doesn't give you the URL to the workflow, or the filename, when running a workflow.
        await this.octokit.rest.actions.listRepoWorkflows({
          ...this.context.repo,
        });
      const workflow_url = workflows.workflows.filter(
        (workflow) => workflow.name === this.context.workflow
      )[0].url;

      await this.#add_failed_label();
      await this.#add_comment(
        `I was unable to cherry-pick this PR; the milestone seems to be missing.

@${
          pull.merged_by.login
        }: Please add the milestone to the PR and re-run the [Auto Cherry-Picker job](${workflow_url}) using the "Run workflow" button.

${this.#run_link}`
      );
      this.core.setFailed(`PR missing milestone.`);
      return null;
    }

    const milestones = await this.#get_relevant_milestones(
      pull.milestone.title
    );
    return {
      pr_num: this.pull_number,
      merge_commit: pull.merge_commit_sha,
      milestones: milestones,
    };
  }

  async cherry_pick_finished(merge_commit_sha, matrix_info) {
    // NB: Unfortunately, we can't have the cherry-pick job use outputs to send the PR numbers, since
    //  it uses a matrix and currently GitHub doesn't support matrix job outputs well
    //  (See https://github.com/orgs/community/discussions/26639#discussioncomment-3252675).
    const infos = await Promise.all(
      matrix_info.map(async ({ branch_name, milestone }) => {
        return this.octokit.rest.pulls.list({
          ...this.#pull_context,
          state: "open",
          head: `${this.context.repo.owner}:${branch_name}`,
        });
      })
    ).then((all_pulls) =>
      all_pulls.map(({ data: pulls }, index) => {
        return { ...matrix_info[index], pr_url: (pulls[0] || {}).html_url };
      })
    );

    let any_failed = false;
    let comment_body =
      "I tried to automatically cherry-pick this change back to each relevant milestone, so that it is available in those older releases of Pants.\n\n";
    infos.forEach(({ pr_url, milestone, branch_name }) => {
      if (pr_url === undefined) {
        any_failed = true;
        comment_body += `## :x: ${milestone}

I was unable to cherry-pick this PR to ${milestone}, likely due to merge-conflicts.

<details>
<summary>Steps to Cherry-Pick locally</summary>

To resolve:
1. (Ensure your git working directory is clean)
2. Run the following script to reproduce the merge-conflicts:
    \`\`\`bash
    git fetch https://github.com/pantsbuild/pants main \\
      && git fetch https://github.com/pantsbuild/pants ${milestone} \\
      && git checkout -b ${branch_name} FETCH_HEAD \\
      && git cherry-pick ${merge_commit_sha}
    \`\`\`
3. Fix the merge conflicts and commit the changes
4. Run \`build-support/cherry_pick/make_pr.sh "${this.pull_number}" "${milestone}"\`

Please note that I cannot re-run CI if a job fails. Please work with your PR approver(s) to re-run CI if necessary.

</details>`;
      } else {
        comment_body += `## :heavy_check_mark: ${milestone}

Successfully opened ${pr_url}.`;
      }
      comment_body += "\n\n";
    });

    comment_body += "---\n\n";
    if (any_failed) {
      comment_body +=
        "When you're done manually cherry-picking, please remove the `needs-cherrypick` label on this PR.\n\n";
    }
    comment_body += "Thanks again for your contributions!\n\n";
    comment_body += this.#run_link;
    await this.#add_comment(comment_body);
    if (any_failed) {
      this.#add_failed_label();
    } else {
      await this.octokit.rest.issues.removeLabel({
        ...this.#issue_context,
        name: "needs-cherrypick",
      });
    }
  }
}

module.exports = CherryPickHelper;
