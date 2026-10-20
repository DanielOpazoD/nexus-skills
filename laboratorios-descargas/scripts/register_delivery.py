#!/usr/bin/env python3
"""Registrar una entrega redactada en la cola activa; no descargar ni reescribir fuentes."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def submit(data, port=8765, *, identity=False):
    base = f'http://127.0.0.1:{port}'
    request = Request(base+('/api/identity/review' if identity else '/api/delivery/register'), data=json.dumps(data).encode(),
                      headers={'Origin':base,'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        try:message = json.load(error).get('error', 'Entrega rechazada.')
        except (ValueError, AttributeError):message = 'Entrega rechazada.'
        raise ValueError(message) from None
    except URLError:
        raise ValueError('Abre el lanzador y reenvía el mismo registro; los archivos locales se conservan.') from None


def main():
    from clinical_request import decode_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--review-identity',action='store_true',help='Registrar cotejo explícito de variantes nominales con encabezado PDF y huella vigentes.')
    args = parser.parse_args()
    try:
        print(json.dumps(submit(decode_json(args.file.read_text()),identity=args.review_identity), ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':main()
