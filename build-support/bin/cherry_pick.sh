#!/usr/bin/env bash
set -e

# (Optional) CLI Args:
#   $1 - PR Number (E.g. "12345")
#   $2 - Milestone (E.g. "2.11.x")
#        this is grabbed off the PR. Useful if you also want to cherry-pick later.

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
if [[ -z $PR_NUM ]]; then
  echo "What's the PR #? (E.g. 8675309)"
  read -r PR_NUM
fi

MILESTONE=$2
if [[ -z $MILESTONE ]]; then
  MILESTONE=$(gh pr view "$PR_NUM" --json milestone --jq '.milestone.title')
  if [[ -z $MILESTONE ]]; then
    echo "No milestone on PR. What's the milestone? (E.g. 2.10.x)"
    read -r MILESTONE
  fi
fi

COMMIT=$(gh pr view "$PR_NUM" --json mergeCommit --jq '.mergeCommit.oid')
TITLE=$(gh pr view "$PR_NUM" --json title --jq '.title')
BODY=$(gh pr view "$PR_NUM" --json body --jq '.body')

if [[ -z $COMMIT ]]; then
  fail "Wasn't able to retrieve merge commit for $PR_NUM."
fi

BRANCH_NAME="cherry-pick-$PR_NUM-to-$MILESTONE"
git fetch https://github.com/pantsbuild/pants "$MILESTONE"
git checkout -b "$BRANCH_NAME" FETCH_HEAD
git cherry-pick "$COMMIT"
gh pr create --base "$MILESTONE" --title "$TITLE (Cherry-pick of #$PR_NUM)" --body "$BODY"

echo "Don't forget to remove the 'needs-cherrypick' label from PR #$PR_NUM!"
