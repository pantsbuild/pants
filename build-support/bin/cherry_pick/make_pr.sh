#!/usr/bin/env bash
set -e


function fail {
  printf '%s\n' "$1" >&2
  exit "${2-1}"
}

if [[ -z $(which gh 2> /dev/null) ]]; then
  fail "Requires the GitHub CLI: https://cli.github.com/"
fi

if [[ -z $(which jq 2> /dev/null) ]]; then
  fail "Requires JQ: https://github.com/jqlang/jq"
fi

PR_NUM=$1
MILESTONE=$2

PR_INFO=$(gh pr view "$PR_NUM" --json title,labels,reviews,body,author)

TITLE=$(echo "$PR_INFO" | jq .title)
AUTHOR=$(echo "$PR_INFO" | jq -r .author.login)
CATEGORY_LABEL=$(echo "$PR_INFO" | jq '.labels[] | select(.name|test("category:.")).name')
REVIEWERS="$(echo "$PR_INFO" | jq -r '.reviews[].author.login' | tr '\n' ' ') $AUTHOR"

BODY_FILE=$(mktemp "/tmp/github.cherrypick.$PR_NUM.XXXXXX")
echo "$PR_INFO" | jq .body > "$BODY_FILE"

gh pr create --base "$MILESTONE" --title "$TITLE (Cherry-pick of #$PR_NUM)" --label "$CATEGORY_LABEL" --body-file "$BODY_FILE" --reviewers "$(echo "$REVIEWERS" | tr ' ' ',')"
rm "$BODY_FILE"
