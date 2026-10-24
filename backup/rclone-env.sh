# Configuração do rclone por variáveis de ambiente (usar com `.`): sem rclone.conf
# em disco. Remote final: b2crypt: (subpastas db/, uploads/, env/).

# 0 se todas as variáveis B2/crypt estão preenchidas; senão 1 e lista em stderr
# só os NOMES faltantes (nunca valores).
rclone_env_check() {
  _missing=
  for _v in B2_ACCOUNT_ID B2_APP_KEY B2_BUCKET CRYPT_PASSWORD CRYPT_SALT; do
    eval "_val=\${$_v:-}"
    [ -n "$_val" ] || _missing="${_missing} ${_v}"
  done
  _val=
  if [ -n "$_missing" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERRO: variáveis ausentes:${_missing}" >&2
    return 1
  fi
  return 0
}

# Exporta RCLONE_CONFIG_*. Senha/salt do crypt são obscurecidos via stdin
# (fora do `ps`); nomes de diretório em claro para o ciclo de vida por prefixo.
rclone_env_export() {
  _pw=$(printf '%s' "$CRYPT_PASSWORD" | rclone obscure -) || return 1
  _pw2=$(printf '%s' "$CRYPT_SALT" | rclone obscure -) || return 1
  export RCLONE_CONFIG_B2_TYPE=b2
  export RCLONE_CONFIG_B2_ACCOUNT="$B2_ACCOUNT_ID"
  export RCLONE_CONFIG_B2_KEY="$B2_APP_KEY"
  export RCLONE_CONFIG_B2_HARD_DELETE=false
  export RCLONE_CONFIG_B2CRYPT_TYPE=crypt
  export RCLONE_CONFIG_B2CRYPT_REMOTE="b2:${B2_BUCKET}/comemore"
  export RCLONE_CONFIG_B2CRYPT_FILENAME_ENCRYPTION=standard
  export RCLONE_CONFIG_B2CRYPT_DIRECTORY_NAME_ENCRYPTION=false
  export RCLONE_CONFIG_B2CRYPT_PASSWORD="$_pw"
  export RCLONE_CONFIG_B2CRYPT_PASSWORD2="$_pw2"
  _pw=; _pw2=
}
