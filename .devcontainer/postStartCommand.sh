#!/usr/bin/env bash

echo "Exporting Pants resolves for use in other tools, such as IDEs..."
# We only cover the simplest cases here. For example, if we change the Python version,
# we will probably have to delete our cache and re-export the resolves.
resolves=(flake8 mypy)
for r in ${resolves[@]}; do
    echo "Checking $r resolve..."
    lockfile_checksum=dist/$r-lockfile.sha256
    # If the virtualenv doesn't exist for the specified resolve
    # or the lockfile has changed, export the resolve.
    if ! test -d dist/export/python/virtualenvs/$r || ! sha256sum -c $lockfile_checksum; then
        ./pants export --resolve=$r
        sha256sum 3rdparty/python/$r.lock > $lockfile_checksum
    fi
done
