#!/usr/bin/env bash
script_dir="$(dirname -- "$(realpath -- "$0")")"
workspace_dir="$(dirname "${script_dir}")"

# helper functions
set_git_config_if_not_set() {
	local key="$1"
	local value="$2"

	# Split the value by comma and iterate over each part
	IFS=',' read -ra ADDR <<<"$value"
	for val in "${ADDR[@]}"; do
		if ! git config --global --get "$key" | grep -q "$val"; then
			git config --global --add "$key" "$val"
		fi
	done
}

set_git_user_info() {
	# Get the credentials from the Git credential helper
	CREDENTIAL_REQUEST=$(
		cat <<EOF
protocol=https
host=github.com
EOF
	)
	CREDENTIALS=$(git credential fill <<<"$CREDENTIAL_REQUEST")

	# Extract the username and password (which is the PAT)
	USERNAME=$(echo "$CREDENTIALS" | grep 'username=' | cut -d '=' -f2)
	PASSWORD=$(echo "$CREDENTIALS" | grep 'password=' | cut -d '=' -f2)

	# Fetch the user information associated with the current credentials
	USER_INFO=$(curl -s -u "$USERNAME:$PASSWORD" https://api.github.com/user)
	USER_EMAILS=$(curl -s -u "$USERNAME:$PASSWORD" https://api.github.com/user/public_emails)

	# Extract the name and email address from the user information
	NAME=$(echo "$USER_INFO" | jq -r '.name')
	EMAIL=$(echo "$USER_EMAILS" | jq -r '.[0].email')

	# Set the Git user.email and user.name configurations
	set_git_config_if_not_set user.email "$EMAIL"
	set_git_config_if_not_set user.name "$NAME"
}

# fix Git safe.directory and ensure user.name and user.email set correctly
set_git_config_if_not_set safe.directory "${workspace_dir}"
set_git_user_info
