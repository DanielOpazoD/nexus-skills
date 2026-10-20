"""Build one offline HTML from the same controls/styles used by the Mini launcher."""
from pathlib import Path
import shutil
import base64
import re,json
from html import escape

def sync_catalog(assets):
    catalog=json.loads((assets/'clinical_catalog.json').read_text())
    # Catálogos canónicos; JS/HTML son derivados, no otra definición del contrato.
    delivery_path=Path(__file__).resolve().parents[2]/'reporte-clinico/references/modelos-entrega.json'
    deliveries=json.loads(delivery_path.read_text())
    catalog['delivery']=deliveries
    (assets/'clinical_catalog.js').write_text('// Generado desde clinical_catalog.json; ejecutar build_portable_form.py.\n'+'globalThis.ClinicalCatalog='+json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+';\n')
    local=(assets/'local_app.html').read_text()
    widget=(assets/'solicitud-examenes.html').read_text()
    options=''.join('<option value="'+escape(m['id'])+'">'+escape(m['label'])+'</option>' for m in deliveries['models'])
    local,n=re.subn(r'(<select id="delivery-model" name="deliveryModel">).*?(</select>)',lambda m:m[1]+options+m[2],local,flags=re.S)
    if n!=1:raise ValueError('Falta selector de entrega.')
    stops=''.join('<button type="button" data-period="'+str(i)+'">'+escape(p['stop'])+'</button>' for i,p in enumerate(catalog['periods']) if p['value']!='latest')
    local,n=re.subn(r'(<div class="period-stops">).*?(</div>)',lambda m:m[1]+stops+m[2],local,flags=re.S)
    if n!=1:raise ValueError('Falta selector de período.')
    maximum=len(catalog['periods'])-2
    local=re.sub(r'(id="period-range" min="0" max=")\d+',lambda m:m[1]+str(maximum),local)
    local=re.sub(r'(<input type="range" min="0" max=")\d+("[^>]*data-source-period=)',lambda m:m[1]+str(maximum+1)+m[2],local)
    for source in ('eloisa','rayen'):
        items=catalog['content'][source]
        labels=''.join('<label><input type="checkbox" name="'+source+'Content" value="'+escape(x['id'])+'"'+(' checked' if x['default'] else '')+'>'+escape(x['label'])+'</label>' for x in items)
        pattern=r'(<details id="'+source+r'-options".*?<fieldset><legend[^>]*>[^<]*</legend>).*?(</fieldset>)'
        local,n=re.subn(pattern,lambda m:m[1]+labels+m[2],local,flags=re.S)
        if n!=1:raise ValueError('Falta contenedor de contenidos en formulario local.')
        labels=''.join('<label style="display:block;margin:8px 0"><input type="checkbox" data-content="'+source+'" value="'+escape(x['id'])+'"'+(' checked' if x['default'] else '')+'> '+escape(x['label'])+'</label>' for x in items)
        pattern=r'(<details data-field="'+source+r'-content-wrap"[^>]*><summary>[^<]*</summary>).*?(</details>)'
        widget,n=re.subn(pattern,lambda m:m[1]+labels+m[2],widget,flags=re.S)
        if n!=1:raise ValueError('Falta contenedor de contenidos en widget.')
    (assets/'local_app.html').write_text(local);(assets/'solicitud-examenes.html').write_text(widget)

def build(assets=None):
    assets = Path(assets) if assets else Path(__file__).resolve().parents[1] / 'assets'
    sync_catalog(assets)
    html = (assets / 'local_app.html').read_text()
    html = re.sub(r'<link rel="stylesheet"[^>]*>|<script src="[^"]+" defer></script>', '', html)
    html = html.replace('<span class="local-badge">Mac mini</span>', '<span class="local-badge">Solicitud para Mac mini</span>')
    html = html.replace('<a href="#history-title" id="history-link">Solicitudes</a>', '<span class="local-badge">Formulario portátil</span>')
    start = html.index('<div class="panel settings-panel">')
    end = html.index('<aside class="sources-panel', start)
    html = html[:start] + '</div>\n' + html[end:]
    html = html[:html.index('</form>') + len('</form>')] + '''
<p class="portable-note">Envía a la carpeta «_Solicitudes Nexo» de Google Drive. El Mac mini confirma la recepción en «acuses».</p>
<p id="copy-status" role="status" aria-live="polite"></p>
<details id="request-preview" class="panel portable-output"><summary>Ver solicitud</summary><textarea id="request-text" rows="8" readonly aria-label="Solicitud para Codex"></textarea></details>
</main></body></html>'''
    html = html.replace('<button id="run" type="submit" disabled>Agregar solicitud <span aria-hidden="true">→</span></button>', '<div class="portable-actions"><button type="button" class="text-button" id="send-drive" disabled>Enviar a Drive</button><button type="button" class="text-button" id="save-request" disabled>Guardar solicitud</button><button id="run" type="submit" disabled>Copiar para Codex <span aria-hidden="true">→</span></button></div>')
    # The extension uses the same controls with external scripts (MV3 CSP).
    names = ('clinical_catalog.js','request_form.js','request_packet.js','portable_app.js','agenda_core.js','agenda_ui.js')
    extension = assets.parent / 'chrome-bridge'
    target = extension / 'request'
    target.mkdir(parents=True, exist_ok=True)
    extension_html = html.replace('Formulario portátil', 'Desde este Mac').replace('/nexo.png','nexo.png')
    shutil.copyfile(assets/'brand/nexo-128.png', target/'nexo.png')
    tags = '<link rel="stylesheet" href="local_app.css">' + ''.join('<script src="'+name+'" defer></script>' for name in names)
    (target/'index.html').write_text(extension_html.replace('</head>', tags+'</head>'))
    for name in ('local_app.css', *names):
        shutil.copyfile(assets/name, target/name)
    shutil.copyfile(assets/'agenda_core.js', extension/'agenda_core.js')
    # Offline HTML supports manual requests; live agenda requires the extension.
    css = (assets/'local_app.css').read_text()
    scripts = '\n'.join((assets/name).read_text() for name in names)
    if '</script' in scripts.lower() or '</style' in css.lower():
        raise ValueError('Unexpected closing tag in embedded source')
    icon = 'data:image/png;base64,' + base64.b64encode((assets/'brand/nexo-128.png').read_bytes()).decode('ascii')
    html = html.replace('/nexo.png',icon)
    policy = "img-src data:; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'"
    html = html.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="'+policy+'"><style>'+css+'</style></head>')
    html = html.replace('</body>', '<script>'+scripts+'</script></body>')
    (assets/'solicitud-portatil.html').write_text(html)
    return html

if __name__ == '__main__':
    build()
    print('Formulario portátil generado.')
