"""Diagnóstico sin envíos ni navegador; evidencia sanitizada por rol."""
from pathlib import Path
import sys
import json
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_httplib2 import AuthorizedHttp
import httplib2
from rpa.config import Settings, timestamp
from rpa.gmail_auth import authorize, client_config
from rpa.runtime import Budget, RPAError
from rpa.store import utcnow


def diagnose(settings):
    result = {'checked_at':utcnow(), 'send_requests':0, 'roles':{}}
    client_config(settings)
    for role in ('remitente', 'receptor'):
        start = time.monotonic()
        try:
            credentials = authorize(settings, Budget(60), role)
            info = {'status':'PROBADO_REAL', 'oauth_loaded':True, 'identity_verified':role=='receptor'}
            if role == 'receptor':
                query = ('after:'+str(int(timestamp(settings.period_start).timestamp()))
                         +' before:'+str(int(timestamp(settings.period_end).timestamp())))
                if settings.gmail_campaign_tag:
                    query += ' subject:"'+settings.gmail_campaign_tag+'"'
                params = dict(userId='me', q=query, maxResults=1)
                if settings.gmail_label == 'ALL':
                    if not settings.gmail_campaign_tag:
                        raise RPAError('GMAIL_ALL_REQUIRES_DATASET')
                    params['includeSpamTrash'] = True
                else:
                    params['labelIds'] = [settings.gmail_label]
                # Librería oficial; desactivar refresh/retry implícito, política controlada por el robot.
                http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=settings.http_timeout),
                                      max_refresh_attempts=0)
                service = build('gmail', 'v1', http=http, cache_discovery=False, static_discovery=True)
                try:
                    page = service.users().messages().list(**params).execute(num_retries=0)
                    info.update(api_enabled_verified=True, list_http=200,
                                messages_on_first_page=len(page.get('messages', [])), next_page=bool(page.get('nextPageToken')))
                finally:
                    service.close()
            else:
                info['status'] = 'TOKEN_DISPONIBLE_ENVIO_NO_PROBADO'
                info['identity_note'] = 'SEND_ONLY_SELECCION_USUARIO_PENDIENTE_RECEPCION'
            result['roles'][role] = info
        except Exception as exc:
            code = exc.code if isinstance(exc, RPAError) else 'HTTP_'+str(exc.resp.status) if isinstance(exc, HttpError) else type(exc).__name__
            result['roles'][role] = {'status':'BLOQUEADO', 'code':code}
        result['roles'][role]['duration_ms'] = round((time.monotonic()-start)*1000, 3)
    target = settings.root / 'docs/evidence/gmail_connection.json'
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    try:
        result = diagnose(Settings.load(Path(__file__).resolve().parents[1]))
        print(json.dumps(result, indent=2))
        raise SystemExit(int(any(r['status']=='BLOQUEADO' for r in result['roles'].values())))
    except RPAError as exc:
        print(exc.code)
        raise SystemExit(1)
