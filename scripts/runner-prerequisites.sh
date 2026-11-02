#!/usr/bin/env bash
set -euo pipefail
# AL2023 already includes AWS CLI on the standard AMI. Keep the system
# interpreter intact; edge jobs install their SDK in a temporary virtualenv.
dnf install -y git python3 python3-pip tar gzip unzip libicu
command -v aws >/dev/null || dnf install -y awscli-2
aws --version
id kairos-runner >/dev/null 2>&1 || useradd --create-home --shell /bin/bash kairos-runner
