-- Ejecutar en el SQL Editor del proyecto Supabase elegido. No contiene secretos.
-- Solo el proceso Python de confianza usa una secret key; nunca el navegador.
begin;
create table if not exists public.rpa_logs (
  id text primary key,
  installation_id uuid not null,
  execution_id text not null,
  kind text not null check (kind in ('execution','event')),
  step_id text not null,
  started timestamptz not null,
  finished timestamptz,
  duration_ms double precision not null check (duration_ms >= 0),
  attempt integer not null check (attempt >= 1),
  retries integer not null check (retries >= 0),
  status text not null,
  level text not null check (level in ('INFO','ERROR','DEBUG')),
  code text not null,
  source text not null,
  send_state text,
  processed integer not null default 0,
  classified integer not null default 0,
  failed integer not null default 0
);
create index if not exists rpa_logs_execution on public.rpa_logs(installation_id,execution_id,started);
create index if not exists rpa_logs_status on public.rpa_logs(status,started);
alter table public.rpa_logs enable row level security;
revoke all on public.rpa_logs from anon, authenticated, service_role;
grant select, insert, update on public.rpa_logs to service_role;
comment on table public.rpa_logs is 'Auditoria RPA sanitizada; sin cuerpos, asuntos, direcciones, tokens o cursores. Sin purga automatica remota.';
commit;
