#!/usr/bin/env python3
"""Importar una solicitud portátil en la cola local, conservando ID y fecha."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from portable_request import parse


def submit(packet, port=8765):
    base = f'http://127.0.0.1:{port}'
    request = Request(base+'/api/import', data=json.dumps(packet).encode(),
                      headers={'Origin':base, 'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        try: message = json.load(error).get('error', 'Solicitud rechazada.')
        except (ValueError, AttributeError): message = 'Solicitud rechazada.'
        raise ValueError(message) from None
    except URLError:
        raise ValueError('Abre el lanzador local y reenvía el mismo archivo; conserva su identificador.') from None
    # No exportar nonce de sesión a prompts o archivos de traslado.
    return {key:result[key] for key in ('id','need','reused')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(submit(parse(args.file.read_text())), ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.error(str(error))

if __name__ == '__main__':
    main()
