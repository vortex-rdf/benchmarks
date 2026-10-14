#!/bin/bash
set -Eeuo pipefail
umask 0022

apply_environment() {
  while IFS='=' read -r setting value; do
    section=${setting#VIRT_}
    section=${section%%_*}
    key=${setting#VIRT_${section}_}
    inifile +inifile /database/virtuoso.ini +section "$section" +key "$key" +value "$value"
  done < <(env | grep -i '^VIRT_' || true)
}

initialize_database() {
  if [[ ! -f /database/virtuoso.ini ]]; then
    cp /opt/virtuoso/database/virtuoso.ini.sample /database/virtuoso.ini

    # The release archive does not include the optional hosting plugins named
    # by the sample file. Keep LoadPath, but remove stale LoadN entries.
    sed -i -E '/^[[:space:]]*Load[0-9]+[[:space:]]*=/d' /database/virtuoso.ini

    apply_environment
    virtuoso-t -f +configfile /database/virtuoso.ini +checkpoint-only
    if [[ "${DBA_PASSWORD:-dba}" != dba ]]; then
      virtuoso-t -f +configfile /database/virtuoso.ini +checkpoint-only \
        +pwdold dba +pwddba "$DBA_PASSWORD" +pwddav "$DBA_PASSWORD"
    fi
  fi
}

case "${1:-start}" in
  start)
    initialize_database
    exec virtuoso-t -f +foreground +configfile /database/virtuoso.ini
    ;;
  version)
    # virtuoso-t -? prints valid version information but returns status 1.
    # Accept only that documented probe status and return success to Docker.
    virtuoso-t '-?' || [[ $? -eq 1 ]]
    ;;
  *) exec "$@" ;;
esac
