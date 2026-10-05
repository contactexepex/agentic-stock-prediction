#!/usr/bin/env bash
# Cloud environment setup script: installs Python dependencies once (cached by the environment).
set -euo pipefail
pip install -q -r requirements.txt
