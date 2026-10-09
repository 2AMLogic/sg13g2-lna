#!/usr/bin/env bash
# Verify that every vendored model file under sim/models/ still matches the
# sha256 recorded for it in sim/models/SOURCE.md. Exit 0 = all match,
# 1 = mismatch (a stamped copy was edited or SOURCE.md is stale), 2 = setup error.
#
#   sim/models/check_sources.sh
#
# SOURCE.md rows are parsed as: a "## <file>" heading followed by a table row
# "| File sha256 | `<64 hex>` |". A "## <file>" section that ends (next "##"
# heading or end of file) without such a row is a FAIL (exit 1): a deleted or
# malformed row must not silently un-stamp a model.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="${here}/SOURCE.md"
[[ -f "${src}" ]] || { echo "check_sources.sh: ${src} not found" >&2; exit 2; }

status=0
n=0
current=""
unstamped() {
  echo "check_sources.sh: FAIL ${current}: section has no 'File sha256' row" >&2
  status=1
}
while IFS= read -r line; do
  if [[ "${line}" =~ ^##[[:space:]]+([^[:space:]]+)[[:space:]]*$ ]]; then
    [[ -z "${current}" ]] || unstamped
    current="${BASH_REMATCH[1]}"
  elif [[ -n "${current}" && "${line}" =~ ^\|[[:space:]]*File\ sha256[[:space:]]*\|[[:space:]]*\`([0-9a-f]{64})\` ]]; then
    want="${BASH_REMATCH[1]}"
    f="${here}/${current}"
    n=$((n + 1))
    if [[ ! -f "${f}" ]]; then
      echo "check_sources.sh: FAIL ${current}: file missing" >&2; status=1; continue
    fi
    got="$(sha256sum "${f}" | awk '{print $1}')"
    if [[ "${got}" == "${want}" ]]; then
      echo "check_sources.sh: OK   ${current} sha256 ${got}"
    else
      echo "check_sources.sh: FAIL ${current}: recorded ${want}, actual ${got}" >&2
      status=1
    fi
    current=""
  fi
done < "${src}"
[[ -z "${current}" ]] || unstamped

if (( n == 0 )); then
  echo "check_sources.sh: no 'File sha256' rows found in ${src}" >&2
  exit 2
fi
exit "${status}"
