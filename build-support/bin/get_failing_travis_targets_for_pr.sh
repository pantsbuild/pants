#!/bin/bash -e

if [[ $# != 1 ]]; then
  echo >&2 "Usage: $0 pull-request-number"
  exit 1
fi
pull=$1

mkdir -p logs/jobs

curl=(curl --fail -s -S -H 'Travis-API-Version: 3')

"${curl[@]}" 'https://api.travis-ci.org/repo/pantsbuild%2Fpants/builds?event_type=pull_request&limit=100&sort_by=finished_at:desc' > logs/search
jobs="$(jq "[ .builds[] | select(.pull_request_number == ${pull}) ][0] | .jobs[].id" logs/search)"
targets=()
for job in ${jobs}; do
  mkdir -p "logs/jobs/${job}"
  "${curl[@]}" "https://api.travis-ci.org/job/${job}" >"logs/jobs/${job}/info"
  state="$(jq -r '.state' "logs/jobs/${job}/info")"
  case "${state}" in
    "passed")
      continue
      ;;
    "failed")
      "${curl[@]}" "https://api.travis-ci.org/job/${job}/log.txt" > "logs/jobs/${job}/txt"
      # WONTFIX: fixing the array expansion is too difficult to be worth it. See https://github.com/koalaman/shellcheck/wiki/SC2207.
      # shellcheck disable=SC2207
      targets=("${targets[@]}" $(cat -v "logs/jobs/${job}/txt" | awk '$2 == "....." && $3 ~ /^FAILURE/ {print $1}'))
      ;;
    *)
      echo >&2 "Job ${job} state ${state}"
      ;;
  esac
done

(for target in "${targets[@]}"; do
  echo "${target}"
done | sort -u)
