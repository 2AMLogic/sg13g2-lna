# Source me:  source sim/env.sh
#
# Resolves the SG13G2 PDK environment (PDK_ROOT/PDK env vars, falling back
# to the usual open_pdks install prefixes: /usr/share/pdk,
# /usr/local/share/pdk, ~/share/pdk, ~/.ciel, ~/.volare), so an interactive
# ngspice session and every sim/*/run_*.sh script agree on which PDK
# install is in use. Follows sg13g2-bandgap/sim/env.sh's and
# sg13g2-opamp/sim/env.sh's shape (same PDK, same resolution order) --
# see sim/README.md "PDK pin" for why this repo reuses that convention
# rather than inventing its own.
#
# Safe to source from any directory; does not require `klt` to be
# installed (this repo's testbenches must remain runnable in a sandbox
# that has ngspice but not klayout-tools).
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

export PDK="${PDK:-ihp-sg13g2}"

if [[ -z "${PDK_ROOT:-}" ]]; then
  for _sg13g2_candidate in /usr/share/pdk /usr/local/share/pdk \
                           "${HOME}/share/pdk" "${HOME}/.ciel" "${HOME}/.volare"; do
    if [[ -d "${_sg13g2_candidate}/${PDK}/libs.tech/ngspice" ]]; then
      export PDK_ROOT="${_sg13g2_candidate}"
      break
    fi
  done
fi

if [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  export SG13G2_NGSPICE_MODELS="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models"
  echo "sg13g2-lna: PDK_ROOT=${PDK_ROOT} PDK=${PDK}"
else
  echo "sg13g2-lna: no ${PDK} install found under PDK_ROOT or the usual prefixes." >&2
  echo "sg13g2-lna: set PDK_ROOT to an open_pdks-shaped IHP-Open-PDK checkout and re-source," >&2
  echo "sg13g2-lna: e.g. via klayout-tools' scripts/fetch-ihp-sg13g2.sh, then:" >&2
  echo "sg13g2-lna:   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2" >&2
  echo "sg13g2-lna: see sim/pdk.json for the pinned release this repo's evidence records target." >&2
fi

unset _sg13g2_candidate
