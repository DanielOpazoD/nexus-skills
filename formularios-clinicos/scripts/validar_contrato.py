#!/usr/bin/env python3
"""Validate shared variable references and form bindings; never reads patient values."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TYPES = {'string', 'date', 'time', 'instant', 'enum', 'boolean', 'number'}
MODES = {'editable', 'linked', 'fixed', 'suppressed'}
FORMATS = {'text', 'date_dmy', 'mark_x'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'Propiedad JSON duplicada: {key}')
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_keys)


def definitions(items, prefix=None):
    require(isinstance(items, list), 'Las variables deben ser una lista.')
    result = {}
    for item in items:
        require(isinstance(item, dict), 'Definición de variable inválida.')
        ident = item.get('id')
        require(isinstance(ident, str) and re.fullmatch(r'[a-z][a-z0-9_]*', ident),
                'ID canónico inválido: usar snake_case en minúsculas.')
        require(ident not in result, f'Variable duplicada: {ident}')
        if prefix:
            require(ident.startswith(prefix + '_'), f'Variable local sin prefijo {prefix}_: {ident}')
        require(isinstance(item.get('label'), str) and item['label'].strip(), f'Falta etiqueta: {ident}')
        require(item.get('type') in TYPES, f'Tipo no admitido: {ident}')
        if item['type'] == 'enum':
            options = item.get('options')
            require(isinstance(options, list) and options and
                    all(isinstance(value, str) and value for value in options), f'Enum inválido: {ident}')
            require(len(set(options)) == len(options), f'Opciones duplicadas: {ident}')
        result[ident] = item
    return result


def validate(catalog, manifest=None, inventory=None):
    require(isinstance(catalog, dict), 'Catálogo inválido.')
    version = catalog.get('version')
    require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version), 'Versión de catálogo inválida.')
    shared = definitions(catalog.get('variables'))
    require(bool(shared), 'El catálogo está vacío.')
    if manifest is None:
        return len(shared), 0
    require(isinstance(manifest, dict), 'Manifiesto inválido.')
    require(manifest.get('catalogVersion') == version, 'Versión de catálogo incompatible.')
    form_id = manifest.get('formId')
    require(isinstance(form_id, str) and re.fullmatch(r'[a-z][a-z0-9_]*', form_id), 'formId inválido.')
    revision = manifest.get('templateRevision')
    require(isinstance(revision, str) and revision.strip(), 'Falta revisión de plantilla.')
    local = definitions(manifest.get('localVariables', []), form_id)
    require(not (shared.keys() & local.keys()), 'Una variable local duplica un ID común.')
    variables = {**shared, **local}
    bindings = manifest.get('bindings')
    require(isinstance(bindings, list) and bindings, 'Faltan bindings.')
    fields, editable = set(), set()
    modes_by_variable = {}
    known_fields = None
    if inventory is not None:
        entries = inventory.get('fields') if isinstance(inventory, dict) else inventory
        require(isinstance(entries, list), 'Inventario de casilleros inválido.')
        known_fields = set()
        for entry in entries:
            field_id = entry.get('id') if isinstance(entry, dict) else entry
            require(isinstance(field_id, str) and field_id.strip(), 'ID inválido en inventario.')
            require(field_id not in known_fields, f'Casillero duplicado en inventario: {field_id}')
            known_fields.add(field_id)
    for binding in bindings:
        require(isinstance(binding, dict), 'Binding inválido.')
        field = binding.get('fieldId')
        require(isinstance(field, str) and field.strip(), 'Falta fieldId.')
        require(field not in fields, f'Casillero duplicado: {field}')
        fields.add(field)
        if known_fields is not None:
            require(field in known_fields, f'Casillero ausente de la plantilla: {field}')
        mode, fmt = binding.get('entryMode'), binding.get('format')
        require(mode in MODES, f'Modo no admitido: {field}')
        require(fmt in FORMATS, f'Formato no admitido: {field}')
        require(type(binding.get('required')) is bool, f'required debe ser booleano: {field}')
        has_variable, has_constant = 'variable' in binding, 'constant' in binding
        require(has_variable != has_constant, f'Usar variable o constant, no ambas ni ninguna: {field}')
        variable = binding.get('variable')
        if has_variable:
            require(isinstance(variable, str) and variable in variables, f'Variable desconocida: {field}')
            require(mode != 'fixed', f'Un dato fijo usa constant: {field}')
            kind = variables[variable]['type']
            modes_by_variable.setdefault(variable, set()).add(mode)
        else:
            require(mode in {'fixed', 'suppressed'}, f'Constante en modo incorrecto: {field}')
            value = binding['constant']
            require(isinstance(value, (str, bool, int, float)) and value is not None,
                    f'Constante inválida: {field}')
            kind = 'boolean' if type(value) is bool else 'string'
        if mode in {'suppressed', 'fixed'}:
            require(not binding['required'], f'Campo suprimido/fijo no puede exigir entrada: {field}')
        if mode == 'editable':
            require(variable not in editable, f'Control repetido: {variable}; usar linked en las copias.')
            editable.add(variable)
        if fmt == 'date_dmy':
            require(kind == 'date', f'date_dmy exige una fecha: {field}')
        if fmt == 'mark_x':
            require(kind == 'boolean' and type(binding.get('equals')) is bool,
                    f'mark_x exige booleano y equals explícito: {field}')
        if binding.get('kind') == 'signature':
            require(mode in {'editable', 'suppressed'}, f'Una firma no se copia ni fija: {field}')
    for variable, modes in modes_by_variable.items():
        require('suppressed' not in modes or modes == {'suppressed'},
                f'Supresión parcial de un dato repetido: {variable}')
    return len(shared), len(bindings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'references/variables.json')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--field-inventory', type=Path,
                        help='JSON de IDs o esquema con fields[].id; no lee geometría PDF.')
    args = parser.parse_args()
    if args.field_inventory and not args.manifest:
        parser.error('--field-inventory requiere --manifest')
    try:
        count, bound = validate(load(args.catalog), load(args.manifest) if args.manifest else None,
                                load(args.field_inventory) if args.field_inventory else None)
    except (ValueError, OSError, TypeError) as error:
        print(f'Contrato inválido: {error}', file=sys.stderr)
        return 1
    print(f'Contrato válido: {count} variables comunes, {bound} casilleros vinculados.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
