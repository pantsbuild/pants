const semver = require('semver')


class CherryPickHelper {
  // @TODO: Document issue_context expected fields
  constructor(octokit, context, issue_context) {
    this.octokit = octokit
    this.context = context
    this.issue_context = {
      ...issue_context,
      pull_number: issue_context.issue_number,
    }
  }

  async get_relevant_milestones(target_milestone) {
    const { data: all_milestones } = await this.octokit.rest.issues.listMilestones({
      ...this.issue_context,
      state: 'open',
    })
    const sorted_milestones = all_milestones.map(milestone => milestone.title).sort((a, b) => semver.compare(semver.coerce(a), semver.coerce(b)))
    const relevant_milestones = sorted_milestones.slice(sorted_milestones.indexOf(target_milestone))
    return relevant_milestones
  }

  async add_failed_label() {
      await this.octokit.rest.issues.addLabels({
        ...this.issue_context,
        labels: ['auto-cherry-picking-failed']
      })
  }

  async cherry_pick_succeeded(created_prs) {
    await this.octokit.rest.issues.removeLabel({
      ...this.issue_context,
      name: 'needs-cherrypick'
    })
    await this.octokit.rest.issues.createComment({
      ...this.issue_context,
      body: `
        @TODO: ...`.replace("        ", "")
    })
  }

  async cherry_pick_failed(merge_commit_sha, milestone) {
    this.add_failed_label()
    const branch_name = `cherry-pick-${this.issue_context.pull_number}-to-${milestone}`
    await this.octokit.rest.issues.createComment({
      ...this.issue_context,
      body: `
        I was unable to cherry-pick this PR to ${milestone}, likely due to merge-conflicts.

        See [the job output](${ this.context.serverUrl}/${this.context.owner}/${this.context.repo}/actions/runs/${this.context.runId}/jobs/${this.context.job })

        To resolve:
        1. (Ensure your git working directory is clean)
        2. Run the following script to reproduce the merge-conflicts:
            \`\`\`bash
            git checkout https://github.com/pantsbuild/pants main \
              && git pull \
              && git fetch https://github.com/pantsbuild/pants ${milestone} \
              && git checkout -b ${branch_name} FETCH_HEAD
              && git cherry-pick ${merge_commit_sha}
            \`\`\`
        3. Fix the merge conflicts, commit the changes, and push the branch to a remote
        4. Run \`pants run build-support/bin/make_cherry_pick_pr.js -- --pull-number="${this.issue_context.pull_number}" --milestone="${milestone}"\`
        `.replace("        ", "")
    })
  }

  async cherry_pick_to_milestone(milestone) {
    const { data: pull } = await this.octokit.rest.pulls.get({
      ...this.issue_context,
    })

    const title = pull.title
    const body = pull.body
    const author = pull.user.login
    const merge_commit = pull.merge_commit_sha
    const category_label = pull.labels.map(label => label.name).filter(label_name => label_name.startsWith("category:"))[0]
    const approvers = await this.octokit.rest.pulls.listReviews({
      ...this.issue_context,
    }).filter(review => review.state === "APPROVED").map(review => review.user.login)
    const pull_reviewers = [
      author,
      ...approvers,
    ]

    // @TODO: git fetch (maybe depth 1) (pantsbuild.pants) (milestone)
    //  if that fails, just log and return

    const branch_name = `cherry-pick-${this.issue_context.pull_number}-to-${milestone}`
    // @TODO: Checkout a new branch based on "FETCH_HEAD"

    // @TODO: git cherry-pick merge_commit
    //  @ TODO: handle if it fails


    // @TODO: Always push (but to where, if not CI?)
    await octokit.rest.pulls.create({
      ...this.issue_context,
      head,
      milestone,
    });

  }

  async

}

module.exports = CherryPickHelper




