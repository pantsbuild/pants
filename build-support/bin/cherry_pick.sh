#!/usr/bin/env bash
set -e

# (Optional) CLI Args:
#   $1 - PR Number (E.g. "12345")
#   $2 - Milestone (E.g. "2.11.x")
#        this is grabbed off the PR. Useful if you also want to cherry-pick later.

function fail {
  printf '%s\n' "$1" >&2
  echo "Don't forget to remove the 'needs-cherrypick' label after making the PR!"
  exit "${2-1}"
}

if [[ -z $(which gh 2> /dev/null) ]]; then
  fail "Requires the GitHub CLI: https://cli.github.com/"
fi

if [[ -n $(git status --porcelain) ]]; then
  fail "Git working directory must be clean."
fi

PR_NUM=$1
if [[ -z $PR_NUM ]]; then
  echo "What's the PR #? (E.g. 8675309)"
  read -r PR_NUM
fi

TARGET_MILESTONE=$2
if [[ -z $TARGET_MILESTONE ]]; then
  TARGET_MILESTONE=$(gh pr view "$PR_NUM" --json milestone --jq '.milestone.title')
  if [[ -z $TARGET_MILESTONE ]]; then
    echo "No milestone on PR. What's the milestone? (E.g. 2.10.x)"
    read -r TARGET_MILESTONE
  fi
fi

MILESTONES=$(gh api graphql -F owner=':owner' -F name=':repo' -f query='
  query ListMilestones($name: String!, $owner: String!) {
    repository(owner: $owner, name: $name) {
      milestones(last: 10) {
        nodes {title}
      }
    }
  }' --jq .data.repository.milestones.nodes.[].title | awk "/$TARGET_MILESTONE/{p=1}p" -)


COMMIT=$(gh pr view "$PR_NUM" --json mergeCommit --jq '.mergeCommit.oid')
TITLE=$(gh pr view "$PR_NUM" --json title --jq '.title')
CATEGORY_LABEL=$(gh pr view "$PR_NUM" --json labels --jq '.labels.[] | select(.name|test("category:.")).name')
if [[ -z $CATEGORY_LABEL ]]; then
  # This happens occasionally, e.g., when cherrypicking the same PR to different branches.
  # Unclear why, but this may help ferret it out.
  echo "Couldn't detect category label on PR. What's the label? (E.g., category:bugfix)"
  read -r CATEGORY_LABEL
fi
REVIEWERS=$(gh pr view "$PR_NUM" --json reviews --jq '.reviews.[].author.login' | sort | uniq)

for MILESTONE in $MILESTONES
do
  BODY_FILE=$(mktemp "/tmp/github.cherrypick.$PR_NUM.$MILESTONE.XXXXXX")
  PR_CREATE_CMD=(gh pr create --base "$MILESTONE" --title "$TITLE (Cherry-pick of #$PR_NUM)" --label "$CATEGORY_LABEL" --body-file "$BODY_FILE")
  while IFS= read -r REVIEWER; do PR_CREATE_CMD+=(--reviewer "$REVIEWER"); done <<< "$REVIEWERS"
  BRANCH_NAME="cherry-pick-$PR_NUM-to-$MILESTONE"

  if [[ -z $COMMIT ]]; then
    fail "Wasn't able to retrieve merge commit for $PR_NUM."
  fi

  gh pr view "$PR_NUM" --json body --jq '.body' > "$BODY_FILE"
  git fetch https://github.com/pantsbuild/pants "$MILESTONE"
  git checkout -b "$BRANCH_NAME" FETCH_HEAD
  git cherry-pick "$COMMIT" ||
    fail "\nPlease fix the above conflicts, commit, and then run:\n  ${PR_CREATE_CMD[*]}"

  "${PR_CREATE_CMD[@]}"
  rm "$BODY_FILE"
done

gh pr edit "$PR_NUM" --remove-label "need-cherrypick"
