// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
const Helper = require("./helper.js");

const OWNER = "pantsbuild";
const REPO = "pants";

function expect_owner_repo(obj) {
  expect(obj.owner).toBe(OWNER);
}

function get_octokit(milestone) {
  return {
    rest: {
      actions: {
        listRepoWorkflows: jest.fn((obj) => {
          return {
            data: {
              workflows: [
                {
                  name: "Auto Cherry-Picker",
                  url: "<WORKFLOW_URL>",
                },
                {
                  name: "CI Green",
                  url: "<OTHER_URL>",
                },
              ],
            },
          };
        }),
      },
      pulls: {
        get: jest.fn((obj) => {
          expect_owner_repo(obj);
          return {
            data: {
              merge_commit_sha: "5b01f3797d102ca97969bef746bfa8d72c75832a",
              milestone: milestone,
              merged_by: {
                login: "steve_buscemi",
              },
            },
          };
        }),
        list: jest.fn(),
      },
      issues: {
        addLabels: jest.fn((obj) => {
          // NB: GitHub's actual code forwarded extra keys to the API, which rejected the data.
          expect(Object.keys(obj)).toEqual([
            "owner",
            "repo",
            "issue_number",
            "labels",
          ]);
        }),
        removeLabel: jest.fn(),
        createComment: jest.fn(),
        listMilestones: jest.fn(),
      },
    },
  };
}

function get_context() {
  return {
    serverUrl: "https://github.com",
    repo: {
      owner: OWNER,
      repo: REPO,
    },
    issue: {
      owner: OWNER,
      repo: REPO,
      number: 19214,
    },
    runId: 5148273558,
    workflow: "Auto Cherry-Picker",
  };
}

function get_core() {
  return {
    setFailed: jest.fn(),
  };
}

test("get_prereqs fails when no milestone", async () => {
  const helper = new Helper({
    octokit: get_octokit(null),
    context: get_context(),
    core: get_core(),
  });

  const result = await helper.get_prereqs();

  expect(result).toBe(null);
  expect(helper.octokit.rest.issues.addLabels).toBeCalledTimes(1);
  expect(helper.octokit.rest.issues.addLabels.mock.calls[0][0].labels).toEqual([
    "auto-cherry-picking-failed",
  ]);
  expect(helper.octokit.rest.issues.createComment).toBeCalledTimes(1);
  expect(
    helper.octokit.rest.issues.createComment.mock.calls[0][0].body
  ).toEqual(
    `I was unable to cherry-pick this PR; the milestone seems to be missing.

@steve_buscemi: Please add the milestone to the PR and re-run the [Auto Cherry-Picker job](<WORKFLOW_URL>) using the "Run workflow" button.

:robot: [Beep Boop here's my run link](https://github.com/pantsbuild/pants/actions/runs/5148273558)`
  );
  expect(helper.core.setFailed).toBeCalledTimes(1);
});

test("get_prereqs ok_with_no_relevant_milestones", async () => {
  const helper = new Helper({
    octokit: get_octokit({ title: "2.16.x" }),
    context: get_context(),
    core: get_core(),
  });

  let project_milestones = [];

  helper.octokit.rest.issues.listMilestones.mockImplementation((obj) => {
    return {
      data: project_milestones.map((title) => {
        return {
          title,
        };
      }),
    };
  });

  project_milestones = ["2.16.x"];
  expect(await helper.get_prereqs()).toEqual({
    merge_commit: "5b01f3797d102ca97969bef746bfa8d72c75832a",
    milestones: ["2.16.x"],
    pr_num: 19214,
  });

  project_milestones = ["2.16.x", "2.17.x"];
  expect(await helper.get_prereqs()).toEqual({
    merge_commit: "5b01f3797d102ca97969bef746bfa8d72c75832a",
    milestones: ["2.16.x", "2.17.x"],
    pr_num: 19214,
  });

  // Some weird ordering
  project_milestones = ["2.17.x", "2.16.x", "2.15.x"];
  expect(await helper.get_prereqs()).toEqual({
    merge_commit: "5b01f3797d102ca97969bef746bfa8d72c75832a",
    milestones: ["2.16.x", "2.17.x"],
    pr_num: 19214,
  });

  // Odd looking milestones
  project_milestones = ["2.17.x", "2.16.x", "2023"];
  expect(await helper.get_prereqs()).toEqual({
    merge_commit: "5b01f3797d102ca97969bef746bfa8d72c75832a",
    milestones: ["2.16.x", "2.17.x"],
    pr_num: 19214,
  });

  // PR milestone is no longer open. That's OK, assume all milestones
  project_milestones = ["2.17.x", "2.18.x"];
  expect(await helper.get_prereqs()).toEqual({
    merge_commit: "5b01f3797d102ca97969bef746bfa8d72c75832a",
    milestones: ["2.17.x", "2.18.x"],
    pr_num: 19214,
  });

  expect(helper.core.setFailed).not.toBeCalled();
});

test("cherry_pick_finished one pass one fail", async () => {
  const helper = new Helper({
    octokit: get_octokit(),
    context: get_context(),
    core: get_core(),
  });

  helper.octokit.rest.pulls.list.mockImplementation((obj) => {
    if (obj.head === "pantsbuild:cherry-pick-19214-to-2.17.x") {
      return {
        data: [{ html_url: `<URL for 2.17.x>` }],
      };
    } else {
      return {
        data: [],
      };
    }
  });

  await helper.cherry_pick_finished("1234ABCD", [
    { branch_name: "cherry-pick-19214-to-2.16.x", milestone: "2.16.x" },
    { branch_name: "cherry-pick-19214-to-2.17.x", milestone: "2.17.x" },
  ]);

  expect(helper.octokit.rest.issues.addLabels).toBeCalledTimes(1);
  expect(helper.octokit.rest.issues.addLabels.mock.calls[0][0].labels).toEqual([
    "auto-cherry-picking-failed",
  ]);
  expect(
    helper.octokit.rest.issues.createComment.mock.calls[0][0].body
  ).toEqual(
    `I tried to automatically cherry-pick this change back to each relevant milestone, so that it is available in those older releases of Pants.

## :x: 2.16.x

I was unable to cherry-pick this PR to 2.16.x, likely due to merge-conflicts.

<details>
<summary>Steps to Cherry-Pick locally</summary>

To resolve:
1. (Ensure your git working directory is clean)
2. Run the following script to reproduce the merge-conflicts:
    \`\`\`bash
    git fetch https://github.com/pantsbuild/pants main \\
      && git fetch https://github.com/pantsbuild/pants 2.16.x \\
      && git checkout -b cherry-pick-19214-to-2.16.x FETCH_HEAD \\
      && git cherry-pick 1234ABCD
    \`\`\`
3. Fix the merge conflicts and commit the changes
4. Run \`build-support/cherry_pick/make_pr.sh "19214" "2.16.x"\`

Please note that I cannot re-run CI if a job fails. Please work with your PR approver(s) to re-run CI if necessary.

</details>

## :heavy_check_mark: 2.17.x

Successfully opened <URL for 2.17.x>.

---

When you're done manually cherry-picking, please remove the \`needs-cherrypick\` label on this PR.

Thanks again for your contributions!

:robot: [Beep Boop here's my run link](https://github.com/pantsbuild/pants/actions/runs/5148273558)`
  );
});

test("cherry_pick_finished all pass", async () => {
  const helper = new Helper({
    octokit: get_octokit(),
    context: get_context(),
    core: get_core(),
  });

  helper.octokit.rest.pulls.list.mockImplementation((obj) => {
    return {
      data: [{ html_url: `<URL for 2.16.x>` }],
    };
  });

  await helper.cherry_pick_finished("1234ABCD", [
    { branch_name: "cherry-pick-19214-to-2.16.x", milestone: "2.16.x" },
  ]);

  expect(helper.octokit.rest.issues.removeLabel).toBeCalledTimes(1);
  expect(helper.octokit.rest.issues.removeLabel.mock.calls[0][0].name).toEqual(
    "needs-cherrypick"
  );
  expect(
    helper.octokit.rest.issues.createComment.mock.calls[0][0].body
  ).toEqual(
    `I tried to automatically cherry-pick this change back to each relevant milestone, so that it is available in those older releases of Pants.

## :heavy_check_mark: 2.16.x

Successfully opened <URL for 2.16.x>.

---

Thanks again for your contributions!

:robot: [Beep Boop here's my run link](https://github.com/pantsbuild/pants/actions/runs/5148273558)`
  );
});
