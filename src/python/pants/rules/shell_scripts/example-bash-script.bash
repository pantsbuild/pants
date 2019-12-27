# Write a file with contents "$1" to the path "$2".
echo "$1" > "$2"

# Write "$3" to stderr.
echo "$3" >&2
