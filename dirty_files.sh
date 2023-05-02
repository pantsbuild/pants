#!/bin/bash
# Replace some random numbers
find src/python/pants -type f -name "*.py" -not -name "__init__.py" | xargs sed -i s/'Copyright [0123456789][0123456789][0123456789][0123456789]'/"Copyright $RANDOM"/
# Wait for the kernel really quick
sleep 1
# Wait for the inotify notifications to stop
while true; do
  mtime=$(stat -c %Y .pants.d/pants.log)
  now=$(date +%s)
  diff=$((now - mtime))
  if (( diff >= 5 )); then
    break
  fi
  sleep $((5 - diff))
done
