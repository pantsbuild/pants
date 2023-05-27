#!/usr/bin/env bash
set -e

# (Optional) CLI Args:
#   $1 - PR Number (E.g. "12345")
#   $2 - remote for pushing (E.g. "origin")
#        The remote to push the cherry-pick branch to.
#        Defaults to prompting.
#        (Please avoid pushing to pantsbuild/pants, and push to your fork instead)

function fail {
  printf '%s\n' "$1" >&2
  exit "${2-1}"
}

function git_fetch_with_depth {
  DEPTH="$1"
  REF="$2"

  # setting --depth will forcibly truncate history, which is fine in the temporary checkout on CI,
  # but would be annoying locally: people will usually already have the full history, so doing a
  # full fetch is fine
  if [[ $CI = true ]]; then
    DEPTH_ARGS=("--depth=$DEPTH")
  else
    DEPTH_ARGS=()
  fi

  git fetch "${DEPTH_ARGS[@]}" https://github.com/pantsbuild/pants "$REF"
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

REMOTE=$2

TARGET_MILESTONE=$(gh pr view "$PR_NUM" --json milestone --jq '.milestone.title')
if [[ -z $TARGET_MILESTONE ]]; then
  fail "No milestone on PR. Please add one or check the PR number."
fi

# NB: Find all milestones >= $TARGET_MILESTONE by having GH list them, then uses awk to trim the
# results to $TARGET_MILESTONE and all milestones after it. Later we will verify these milestones
# match a branch name.
# shellcheck disable=SC2016
MILESTONES=$(gh api graphql -F owner=":owner" -F name=":repo" -f query='
  query ListMilestones($name: String!, $owner: String!) {
    repository(owner: $owner, name: $name) {
      milestones(last: 10) {
        nodes {title}
      }
    }
  }' --jq .data.repository.milestones.nodes.[].title | sort -V | awk "/$TARGET_MILESTONE/{p=1}p" -)

COMMIT=$(gh pr view "$PR_NUM" --json mergeCommit --jq '.mergeCommit.oid')
if [[ -z $COMMIT ]]; then
  fail "Wasn't able to retrieve merge commit for $PR_NUM."
fi
# Both the commit and its parent are required, to compute the diff to apply when cherry picking
git_fetch_with_depth 2 "$COMMIT"

TITLE=$(gh pr view "$PR_NUM" --json title --jq '.title')
CATEGORY_LABEL=$(gh pr view "$PR_NUM" --json labels --jq '.labels.[] | select(.name|test("category:.")).name')
if [[ -z $CATEGORY_LABEL ]]; then
  # This happens occasionally, e.g., when cherrypicking the same PR to different branches.
  # Unclear why, but this may help ferret it out.
  echo "Couldn't detect category label on PR. What's the label? (E.g., category:bugfix)"
  read -r CATEGORY_LABEL
fi

REVIEWERS=$(gh pr view "$PR_NUM" --json reviews --jq '.reviews.[].author.login' | sort | uniq)

BODY_FILE=$(mktemp "/tmp/github.cherrypick.$PR_NUM.XXXXXX")
gh pr view "$PR_NUM" --json body --jq '.body' > "$BODY_FILE"

for MILESTONE in $MILESTONES; do
  # Only the HEAD is required to be able to create the cherry-pick branch, so there's no need to
  # spend time cloning the whole history
  git_fetch_with_depth 1 "$MILESTONE" || continue

  PR_CREATE_CMD=(gh pr create --base "$MILESTONE" --title "$TITLE (Cherry-pick of #$PR_NUM)" --label "$CATEGORY_LABEL" --body-file "$BODY_FILE")
  while IFS= read -r REVIEWER; do PR_CREATE_CMD+=(--reviewer "$REVIEWER"); done <<< "$REVIEWERS"
  # NB: Add the author in case someone else creates the PR
  PR_CREATE_CMD+=(--reviewer "$(gh pr view "$PR_NUM" --json author --jq '.author.login')")
  BRANCH_NAME="cherry-pick-$PR_NUM-to-$MILESTONE"
  git checkout -b "$BRANCH_NAME" FETCH_HEAD
  if git cherry-pick "$COMMIT"; then
    if [[ -n $REMOTE ]]; then
      git push -u "$REMOTE" "$BRANCH_NAME"
    fi
    "${PR_CREATE_CMD[@]}"
  else
    readarray -t -d '' ESCAPED_PR_CREATE_CMD < <(printf "%q\0" "${PR_CREATE_CMD[@]}")
    fail "
    Cherry-picking failed, likely due to a merge-conflict.
    Please fix the above conflicts, commit, and then run the following command.
    (Also don't forget to remove the 'needs-cherrypick' label from the original PR).

      ${ESCAPED_PR_CREATE_CMD[*]}
    "
  fi
done
rm "$BODY_FILE"

gh pr edit "$PR_NUM" --remove-label "needs-cherrypick"
