"""Start im Container: HTTPS (eigenes Zertifikat) und, je nach Stack-Datei, HTTP mit Umleitung.

Umgebungsvariablen:
- PORT (8000): unverschlüsselter Port im Container
- TLS_PORT (8443): HTTPS-Port im Container
- HTTPS_PORT: Port, unter dem HTTPS von außen erreichbar ist (z. B. 443). Ist er gesetzt, leitet der
  unverschlüsselte Port alles auf HTTPS um. Ohne ihn bleibt HTTP wie bisher nutzbar (Übergang), und die
  Seiten zeigen einen Hinweis.
- HTTPS=0: kein HTTPS (z. B. hinter einem eigenen Proxy, auf eigene Verantwortung)."""
import asyncio
import json
import os

import uvicorn

from . import tls


def redirect_app(public_port):
    """Kleine ASGI-App: /healthz beantworten, alles andere auf HTTPS umleiten."""
    async def app(scope, receive, send):
        if scope['type'] != 'http':
            return
        if scope.get('path') == '/healthz':
            body = json.dumps({'ok': True}).encode()
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]})
            return await send({'type': 'http.response.body', 'body': body})
        host = dict(scope.get('headers') or []).get(b'host', b'').decode('latin-1')
        name = host.rsplit(':', 1)[0] if not host.endswith(']') else host  # Port abschneiden, IPv6 [..] lassen
        if not name or any(c in name for c in '/\\@ '):
            name = 'localhost'
        port = '' if public_port == '443' else f':{public_port}'
        qs = scope.get('query_string', b'').decode('latin-1')
        loc = f'https://{name}{port}{scope.get("path", "/")}' + (f'?{qs}' if qs else '')
        await send({'type': 'http.response.start', 'status': 308,
                    'headers': [(b'location', loc.encode()), (b'content-length', b'0')]})
        await send({'type': 'http.response.body', 'body': b''})
    return app


async def main():
    port, tls_port = int(os.getenv('PORT', '8000')), int(os.getenv('TLS_PORT', '8443'))
    public = os.getenv('HTTPS_PORT', '').strip()
    if os.getenv('HTTPS', '1').strip() == '0':
        await uvicorn.Server(uvicorn.Config('app.main:app', host='0.0.0.0', port=port)).serve()
        return
    tls.ensure()
    key, cert, _ = tls.paths()
    servers = [uvicorn.Server(uvicorn.Config('app.main:app', host='0.0.0.0', port=tls_port,
                                             ssl_keyfile=str(key), ssl_certfile=str(cert)))]
    if public.isdigit():
        servers.append(uvicorn.Server(uvicorn.Config(redirect_app(public), host='0.0.0.0', port=port)))
    else:
        servers.append(uvicorn.Server(uvicorn.Config('app.main:app', host='0.0.0.0', port=port)))
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == '__main__':
    asyncio.run(main())
