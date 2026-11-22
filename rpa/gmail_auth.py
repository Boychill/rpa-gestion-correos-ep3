"""OAuth explícito por rol. Sin navegador en operación normal; secretos con ACL y DPAPI."""
import base64
import json
import os
from pathlib import Path
import sys
import uuid

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import httpx

from rpa.runtime import RPAError, profile_lock

SCOPES = {'remitente': ['https://www.googleapis.com/auth/gmail.send'],
          'receptor': ['https://www.googleapis.com/auth/gmail.readonly']}


def restrict(path, directory=False):
    if sys.platform == 'win32':
        import win32api, win32con, win32security
        handle = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(handle, win32security.TokenUser)[0]
        finally:
            handle.Close()
        acl = win32security.ACL()
        flags = (win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE) if directory else 0
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, win32con.GENERIC_ALL, sid)
        system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, win32con.GENERIC_ALL, system)
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    else:
        path.chmod(0o700 if directory else 0o600)


def atomic_private(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict(path.parent, directory=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as file:
            restrict(temporary)
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
        restrict(path)
    finally:
        temporary.unlink(missing_ok=True)


def client_config(settings):
    path = (settings.root / settings.gmail_client_file).resolve()
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        installed = config['installed']
        if (not installed.get('client_id') or not installed.get('client_secret')
                or installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth'
                or installed.get('token_uri') != 'https://oauth2.googleapis.com/token'):
            raise ValueError()
        return config
    except FileNotFoundError as exc:
        raise RPAError('GMAIL_OAUTH_CLIENT_REQUIRED') from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise RPAError('GMAIL_DESKTOP_CLIENT_INVALID') from exc


def token_path(settings, role):
    return (settings.root / (settings.gmail_sender_token_path if role == 'remitente'
                            else settings.gmail_receiver_token_path)).resolve()


def save_token(path, credentials, role, account):
    value = dict(role=role, declared_account=account, credentials=json.loads(credentials.to_json()))
    raw = json.dumps(value).encode('utf-8')
    if sys.platform == 'win32':
        import win32crypt
        raw = json.dumps({'format':'dpapi-v1', 'encrypted':base64.b64encode(
            win32crypt.CryptProtectData(raw, 'RPA Gmail '+role, None, None, None, 0)).decode()}).encode()
    atomic_private(path, raw)


def read_token(path):
    try:
        data = json.loads(path.read_bytes())
        if data.get('format') == 'dpapi-v1':
            import win32crypt
            data = json.loads(win32crypt.CryptUnprotectData(base64.b64decode(data['encrypted']), None, None, None, 0)[1])
        return data
    except Exception as exc:
        raise RPAError('AUTH_REQUIRED') from exc


def refresh(credentials, settings, budget):
    class TimedRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs['timeout'] = min(settings.http_timeout, budget.remaining())
            return super().__call__(*args, **kwargs)
    try:
        credentials.refresh(TimedRequest())
    except TransportError as exc:
        raise RPAError('AUTH_TRANSIENT') from exc
    except RefreshError as exc:
        raise RPAError('AUTH_TRANSIENT' if getattr(exc, 'retryable', False) else 'AUTH_REQUIRED') from exc


def receiver_profile(credentials, account, settings, budget):
    try:
        with httpx.Client(timeout=min(settings.http_timeout, budget.remaining()), follow_redirects=False) as client:
            response = client.get('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                                  headers={'Authorization':'Bearer '+credentials.token})
        if response.status_code != 200:
            from rpa.gmail_errors import error_code
            raise RPAError(error_code(response))
        profile = response.json()
        if profile.get('emailAddress', '').lower() != account.lower():
            raise RPAError('GMAIL_ACCOUNT_MISMATCH')
        return profile
    except (httpx.TransportError, ValueError) as exc:
        raise RPAError('AUTH_TRANSIENT') from exc


def authorize(settings, budget, role='receptor', interactive=False, force=False, refresh_existing=False):
    if role not in SCOPES:
        raise RPAError('GMAIL_ROLE_INVALID')
    account = settings.gmail_sender_address if role == 'remitente' else (settings.gmail_receiver_address or settings.mailbox)
    if not account:
        raise RPAError('GMAIL_ADDRESS_REQUIRED')
    config = client_config(settings)
    path = token_path(settings, role)
    scopes = SCOPES[role]
    with profile_lock(settings.runtime / 'locks' / ('gmail-auth-'+role+'.lock')):
        credentials = None
        if path.exists() and not force:
            data = read_token(path)
            info = data.get('credentials', {})
            if (data.get('role') != role or data.get('declared_account', '').lower() != account.lower()
                    or info.get('client_id') != config['installed']['client_id']):
                raise RPAError('AUTH_REQUIRED')
            if set(info.get('scopes', [])) != set(scopes):
                raise RPAError('AUTH_SCOPE_MISMATCH')
            credentials = Credentials.from_authorized_user_info(info, scopes=scopes)
            if not credentials.valid or refresh_existing:
                refresh(credentials, settings, budget)
        if credentials is None:
            if not interactive:
                raise RPAError('AUTH_REQUIRED')
            try:
                flow = InstalledAppFlow.from_client_config(config, scopes, autogenerate_code_verifier=True)
                credentials = flow.run_local_server(host='localhost', port=0, open_browser=True,
                    timeout_seconds=min(settings.oauth_timeout_seconds, budget.remaining()),
                    authorization_prompt_message='', success_message='Autorización recibida. Puedes cerrar esta ventana.',
                    login_hint=account, prompt='consent select_account', access_type='offline')
            except Exception as exc:
                raise RPAError('AUTHORIZATION_FAILED') from exc
        # SEND no habilita getProfile: cuenta declarada, identidad a contrastar en recepción.
        if not credentials.has_scopes(scopes):
            raise RPAError('AUTH_SCOPE_MISMATCH')
        if role == 'receptor':
            try:
                receiver_profile(credentials, account, settings, budget)
            except RPAError as exc:
                if exc.code in {'GMAIL_API_DISABLED', 'AUTH_TRANSIENT'}:
                    # Conservar el consentimiento sin afirmar identidad verificada.
                    # Toda carga posterior vuelve a comprobar el perfil antes de usar el buzón.
                    save_token(path, credentials, role, account)
                raise
        save_token(path, credentials, role, account)
        return credentials


def authorize_with_audit(settings, role, force=False):
    """Autorización manual: también genera auditoría local y Supabase, sin enviar correo."""
    import time
    from rpa.runtime import Audit, Budget
    from rpa.store import Store, utcnow, encode
    from rpa.log_files import finish_logging
    execution_id, started, timer = str(uuid.uuid4()), utcnow(), time.monotonic()
    with Store(settings.runtime/'state.sqlite3', settings.root) as store:
        store.execute('INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)',
            (execution_id, 'gmail-auth-'+role, 'gmail-auth-v2', started, 'RUNNING', 'GMAIL_AUTH'))
        audit, status = Audit(store, execution_id, settings.runtime/'logs'), 'REVIEW'
        try:
            with audit.step('oauth_authorize', context={'role':role, 'recovery':'EXPLICIT_AUTHORIZATION'}):
                result = authorize(settings, Budget(settings.oauth_timeout_seconds+60), role,
                                   interactive=True, force=force)
            status = 'COMPLETED'
            return result
        finally:
            metrics = {'duration_seconds':round(time.monotonic()-timer,3), 'processed':0,
                       'failed':int(status!='COMPLETED'), 'retries':0}
            store.execute('UPDATE executions SET status=?,finished=?,metrics=? WHERE id=?',
                          (status,utcnow(),encode(metrics),execution_id))
            audit.close()
            finish_logging(settings, store, execution_id)
