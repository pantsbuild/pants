#!/usr/bin/env bash
#
# Outputs package info (in yaml format) for all installed packages
# with non-standard or additional top level modules.
#
# Usage: ./build-support/python/find_module_mappings.sh [.../site-packages]
#
# Will look up default site packages for current python unless
# provided.

site_packages="${1:-`python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"`}"

function extra_top_levels {
    for module in $(cat "$2"); do
        case "${module,,}" in
            $1|tests|_*) ;;
            *) echo "  - $module" ;;
        esac
    done
}

for top_level in $(find "$site_packages" -name top_level.txt | sort); do
    package=${top_level#$site_packages/}
    package=${package%%-*}
    package=${package,,}
    case "$package" in
        */*) ;;  # skip if there is / in package name
        *)
            top_levels=$(extra_top_levels "$package" "$top_level")
            [ -z "$top_levels" ] || cat <<EOF
$package:
$top_levels

EOF
    esac
done
