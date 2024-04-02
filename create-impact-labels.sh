#!/usr/bin/env bash
set -eo pipefail

USAGE='create-impact-labels.sh <owner/repo>'
DESCRIPTION='

  Uses gh cli to create a set of impact:n issue labels via REST API

  You must have already authenticated the gh cli to github either
  via interactive login or via access token.

  Dependencies: requires gh cli to be installed.
'

function usage() {
	echo "$USAGE" "$DESCRIPTION" >&2
}

type gh >/dev/null 2>&1 || {
	echo >&2 "Error: gh cli must be installed (try brew install gh)"
	usage
	exit 1
}

[ $# -ge 1 ] || {
	usage
	exit 1
}

REPO="$1"

gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/labels" \
    -f name='impact:1' \
    -f color='bfe5be' \
    -f description='This issue represents 1 customer value point'

gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/labels" \
    -f name='impact:2' \
    -f color='bfe5bd' \
    -f description='This issue represents 2 customer value points'

gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/labels" \
    -f name='impact:3' \
    -f color='bfe5bc' \
    -f description='This issue represents 3 customer value points'

gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/labels" \
    -f name='impact:4' \
    -f color='bfe5bb' \
    -f description='This issue represents 4 customer value points'

gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/labels" \
    -f name='impact:5' \
    -f color='bfe5ba' \
    -f description='This issue represents 5 customer value points'
