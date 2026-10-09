#!/usr/bin/env bash
# fetch-pcell-deps.sh -- fetch the two git-submodule shims IHP's native
# PyCell library needs to run headless, at the exact commits the pinned
# PDK release (sim/pdk.json: IHP-Open-PDK v0.3.0) records for them.
#
#   layout/tools/fetch-pcell-deps.sh          # fetch + verify (idempotent)
#   layout/tools/fetch-pcell-deps.sh --check  # verify only, exit 3 if absent
#
# WHY THIS EXISTS
#
# layout/lna_core/generate.py draws every device with the PDK's OWN PyCells
# (ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib), not hand-drawn
# footprints. That library imports two packages IHP-Open-PDK carries as git
# submodules, which a release-tarball fetch (the fetch method sim/pdk.json
# records) leaves EMPTY:
#
#   libs.tech/klayout/python/pypreprocessor      -> IHP-GmbH/pypreprocessor
#   libs.tech/klayout/python/pycell4klayout-api  -> IHP-GmbH/pycell4klayout-api
#
# The PyPI `pypreprocessor` 0.7.7 sdist does not build on Python 3.14, and a
# host's PDK install may carry a different pycell4klayout-api revision than
# the one the pinned release records (checked: this repo's development host
# did). So both are fetched here at the submodule commits recorded in the
# IHP-Open-PDK v0.3.0 tree, sha256-verified, into layout/build/pcell-deps/
# (gitignored, generated). Nothing is installed host-wide.
#
# Pins: the submodule SHAs below are what
#   gh api 'repos/IHP-GmbH/IHP-Open-PDK/contents/ihp-sg13g2/libs.tech/klayout/python/<name>?ref=v0.3.0' --jq .sha
# returns; the sha256 values are of GitHub's archive tarball for that SHA.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/../build/pcell-deps"

PYPREPROCESSOR_REPO="IHP-GmbH/pypreprocessor"
PYPREPROCESSOR_SHA="cf1ff9bad0fb5338cf1c5b990b2b816b1ea01a64"
PYPREPROCESSOR_TGZ_SHA256="b24070ad2f931fe42fd12c02cf8ca5d65846e07b4e8276e5787ef2ceab65b76d"

PYCELL_API_REPO="IHP-GmbH/pycell4klayout-api"
PYCELL_API_SHA="4c463c43991fb0967a824906518b66047bfb33c4"
PYCELL_API_TGZ_SHA256="bb18d75b4cd9577058b5cf34d7ad460893b322d123453b52901dfa7c58ef278b"

check_only=0
if [[ "${1:-}" == "--check" ]]; then
  check_only=1
fi

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# fetch_one <repo> <sha> <tgz-sha256> <dest-subdir>
fetch_one() {
  local repo="$1" sha="$2" want="$3" sub="$4"
  local out="${DEST}/${sub}"
  local stamp="${out}/.fetched-sha"
  if [[ -f "${stamp}" && "$(cat "${stamp}")" == "${sha}" ]]; then
    echo "fetch-pcell-deps: ${sub} @ ${sha} present"
    return 0
  fi
  if (( check_only )); then
    echo "fetch-pcell-deps: ${sub} @ ${sha} missing -- run layout/tools/fetch-pcell-deps.sh" >&2
    exit 3
  fi
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL -o "${tmp}/src.tgz" "https://github.com/${repo}/archive/${sha}.tar.gz"
  local got
  got="$(sha256_of "${tmp}/src.tgz")"
  if [[ "${got}" != "${want}" ]]; then
    echo "fetch-pcell-deps: sha256 mismatch for ${repo}@${sha}: got ${got}, want ${want}" >&2
    rm -rf "${tmp}"
    exit 1
  fi
  rm -rf "${out}"
  mkdir -p "${out}"
  tar -xzf "${tmp}/src.tgz" -C "${out}" --strip-components=1
  echo "${sha}" > "${stamp}"
  rm -rf "${tmp}"
  echo "fetch-pcell-deps: ${sub} @ ${sha} fetched (sha256 ${got})"
}

# The PyCell library imports `pypreprocessor.pypreprocessor`: the submodule
# checkout root is itself the outer `pypreprocessor` namespace package, so
# it lands one directory down from the path root added to sys.path.
fetch_one "${PYPREPROCESSOR_REPO}" "${PYPREPROCESSOR_SHA}" "${PYPREPROCESSOR_TGZ_SHA256}" "root/pypreprocessor"
fetch_one "${PYCELL_API_REPO}" "${PYCELL_API_SHA}" "${PYCELL_API_TGZ_SHA256}" "pycell4klayout-api"
