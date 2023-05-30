#!/usr/bin/env bash
set -e

# CLI Args:
#   $1 - PR Number (E.g. "12345")
#   $2 - Milestone

function fail {
  printf '%s\n' "$1" >&2
  exit "${2-1}"
}

if [[ -z $(which gh 2> /dev/null) ]]; then
  fail "Requires the GitHub CLI: https://cli.github.com/"
fi

if [[ -n $(git status --porcelain) ]]; then
  fail "Git working directory must be clean."
fi

PR_NUM=$1
TARGET_MILESTONE=$2

COMMIT=$(gh pr view "$PR_NUM" --json mergeCommit --jq '.mergeCommit.oid')
if [[ -z $COMMIT ]]; then
  fail "Wasn't able to retrieve merge commit for $PR_NUM."
fi

TITLE=$(gh pr view "$PR_NUM" --json title --jq '.title')
CATEGORY_LABEL=$(gh pr view "$PR_NUM" --json labels --jq '.labels.[] | select(.name|test("category:.")).name')
REVIEWERS=$(gh pr view "$PR_NUM" --json reviews --jq '.reviews.[].author.login' | sort | uniq)
BODY_FILE=$(mktemp "/tmp/github.cherrypick.$PR_NUM.XXXXXX")
BRANCH_NAME="cherry-pick-$PR_NUM-to-$MILESTONE"

gh pr view "$PR_NUM" --json body --jq '.body' > "$BODY_FILE"

PR_CREATE_CMD=(gh pr create --base "$MILESTONE" --title "$TITLE (Cherry-pick of #$PR_NUM)" --label "$CATEGORY_LABEL" --body-file "$BODY_FILE")
while IFS= read -r REVIEWER; do PR_CREATE_CMD+=(--reviewer "$REVIEWER"); done <<< "$REVIEWERS"
# NB: Add the author in case someone else creates the PR (like WorkerPants)
PR_CREATE_CMD+=(--reviewer "$(gh pr view "$PR_NUM" --json author --jq '.author.login')")

git fetch https://github.com/pantsbuild/pants "$MILESTONE"
git checkout -b "$BRANCH_NAME" FETCH_HEAD

if git cherry-pick "$COMMIT"; then
  if [[ $CI = true ]]; then
    # By default, `gh pr create` mirrors the branch to the relevant git remote, but does so by
    # prompting the user. To workaround this in CI, we push the branch ourselves.
    git push -u origin "$BRANCH_NAME"
  fi
  "${PR_CREATE_CMD[@]}"
else
  readarray -t -d '' ESCAPED_PR_CREATE_CMD < <(printf "%q\0" "${PR_CREATE_CMD[@]}")
  fail "
  Cherry-picking failed, likely due to a merge-conflict.
  Please fix the above conflicts, commit, and then run the following command.

    ${ESCAPED_PR_CREATE_CMD[*]}
  "
fi

rm "$BODY_FILE"
