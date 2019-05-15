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
 read -rp "What sha was the last release made from?: " LAST_RELEASE_SHA
elif [[ "$1" == "-h" ]]
then
  help
else
  LAST_RELEASE_SHA="$1"
fi

echo
echo "Potentially relevant headers:"
echo "----------------------------------------------------------------------------------------------------"
cat <<EOF

API Changes
~~~~~~~~~~~


New Features
~~~~~~~~~~~~


Bugfixes
~~~~~~~~


Refactoring, Improvements, and Tooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


Documentation
~~~~~~~~~~~~~


EOF

echo
echo "Changes since ${LAST_RELEASE_SHA}:"
echo "----------------------------------------------------------------------------------------------------"
echo

for sha in $(git log --format="format:%H" HEAD "^${LAST_RELEASE_SHA}")
do
  subject=$(git log -1 --format="format:%s" "$sha")
  echo "* ${subject}"

  urls=()
  urls=(
    "${urls[@]}"
    $(
      git log -1 --oneline "${sha}" | \
        grep -Eo "\(#[0-9]+\)" | \
        sed -Ee "s|^\(#([0-9]+)\)$|https://github.com/pantsbuild/pants/pull/\1|"
    )
  )
  urls=(
    "${urls[@]}"
    $(
      git log -1 "${sha}" --format="format:%b" | \
        grep -E "https?://" | \
        sed -Ee "s|^.*(https?://[^ ]+).*$|\1|" | \
        grep -v travis-ci.org | \
        sed -Ee "s|[/\.]+$||"
    )
  )

  for url in "${urls[@]}"
  do
    if echo "${url}" | grep github.com | grep -q /issues/
    then
      issue=${url##*/}
      echo "  \`Issue #${issue} <${url}>\`_"
    fi
  done

  for url in "${urls[@]}"
  do
    if echo "${url}" | grep github.com | grep -q /pull/
    then
      issue=${url##*/}
      echo "  \`PR #${issue} <${url}>\`_"
    fi
  done

  echo
done
