#!/bin/zsh
set -e
skill_dir="${0:A:h}"
lock_hash=$(shasum -a 256 "$skill_dir/requirements.lock")
lock_hash="${lock_hash[1,16]}"
runtime_dir="$HOME/Library/Application Support/HHR Clinical/runtime/$lock_hash"
if [[ -n "${LABS_PYTHON:-}" ]]; then
  runtime_python="$LABS_PYTHON"
elif [[ -x "$runtime_dir/bin/python3" && -f "$runtime_dir/runtime.ok" ]]; then
  runtime_python="$runtime_dir/bin/python3"
else
  print -u2 "Falta el entorno verificado. Ejecuta scripts/setup_runtime.py con Python 3.12; consulta references/instalacion.md."
  exit 1
fi
exec "$runtime_python" "$skill_dir/scripts/local_launcher.py" "$@"
