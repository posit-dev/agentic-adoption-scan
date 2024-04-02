#!/usr/bin/env bash
set -eo pipefail

USAGE='record-deployment <owner/repo> <ref> <environment>'
DESCRIPTION='

  Uses gh cli to create a GitHub deployment via REST API

  You must have already authenticated the gh cli to github either
  via interactive login or via access token.

  Dependencies: requires gum, jq, and gh cli to be installed.
'

function usage() {
	echo "$USAGE" "$DESCRIPTION" >&2
}

type gh >/dev/null 2>&1 || {
	echo >&2 "Error: gh cli must be installed (try brew install gh)"
	usage
	exit 1
}

type jq >/dev/null 2>&1 || {
	echo >&2 "Error: jq cli must be installed (try brew install jq)"
	usage
	exit 1
}

type gum >/dev/null 2>&1 || {
	echo >&2 "Error: gum cli must be installed (try brew install gum)"
	usage
	exit 1
}

[ $# -ge 3 ] || {
	usage
	exit 1
}

REPO="$1"
REF="$2"
ENV="$3"

RESULT=$(
	gh api \
		--method POST \
		-H "Accept: application/vnd.github+json" \
		-H "X-GitHub-Api-Version: 2022-11-28" \
		"/repos/${REPO}/deployments" \
		-f ref="${REF}" \
		-f payload='{ "deploy": "engineering effectiveness testing" }' \
		-f description='Recording a deploy event from gh cli' \
		-f environment="${ENV}"
)

# we need the deployment ID from the json response. If there was an error
# such as a github PAT that has not yet been authorized for use with the
# github org or a repo name that doesn't exist, then the gh command will
# error and the script will have already exited by this point.
ID=$(echo "${RESULT}" | jq -r '.id')

#echo "ID was $ID"

# Here is where you would do the deployment work, such as calling the
# PTD patch API to deploy a new container
gum spin --title="Running a simulated deployment..." sleep 3

# After the deployment is complete, you can update the deployment status
# to indicate success or failure. Here we are just updating the status
# to succeeded.
# https://docs.github.com/en/rest/deployments/statuses?apiVersion=2022-11-28#create-a-deployment-status

LOG_URL=""
RESULT=$(gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/${REPO}/deployments/${ID}/statuses" \
  -f environment="${ENV}" \
  -f state='success' \
  -f log_url="${LOG_URL}" \
  -f description='Deployment finished successfully.'
)

gum log --time=kitchen "Visit https://github.com/${REPO}/deployments/${ENV}" to see the new deployment status.
