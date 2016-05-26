#!/usr/bin/env bash

function help() {
  echo "Usage: $0 [-h|<sha>]"
  echo
  echo "  -h  display this help"
  echo "  With no arguments, prompts for the last release sha"
  echo
  echo "Attempts to generate a mostly complete changelog .rst section"
  echo "given the last release sha.  Each commit since that sha will"
  echo "have an RST compatible bullet generated with commit summary"
  echo "and ISSUE/RB links if present in the commit message.  A"
  echo "header not intended for the changelog is included to provide"
  echo "information about the commit in case more investigation is"
  echo "needed."
  if (( $# > 0 ))
  then
    echo
    echo "$@"
    exit 1
  else
    exit
  fi
}

if (( $# > 1 ))
then
  help "Too many arguments."
elif (( $# == 0 ))
then
 read -p "What sha was the last release made from?: " LAST_RELEASE_SHA
elif [[ "$1" == "-h" ]]
then
  help
else
  LAST_RELEASE_SHA="$1"
fi

change_count=$(git rev-list HEAD ^${LAST_RELEASE_SHA} | wc -l)
git log --format="format:%H %s" HEAD ^${LAST_RELEASE_SHA} | {

  echo
  echo "There have been ${change_count} changes since the last release."
  echo

  while read sha subject
  do
    urls=()
    urls=(
      ${urls}
      $(
        git log -1 ${sha} --format="format:%b" | \
          grep -E "https?://" | \
          sed -Ee "s|^.*(https?://[^ ]+).*$|\1|" | \
          grep -v travis-ci.org | \
          sed -Ee "s|[/\.]+$||"
      )
    )

    echo "* ${subject}"

    for url in ${urls[@]}
    do
      if echo ${url} | grep github.com | grep -q /issues/
      then
        issue=${url##*/}
        echo "  \`Issue #${issue} <${url}>\`_"
      fi
    done

    for url in ${urls[@]}
    do
      if echo ${url} | grep -q rbcommons.com
      then
        rb=${url##*/}
        echo "  \`RB #${rb} <${url}>\`_"
      fi
    done

    echo
  done
}
