-- Ampliación compatible: ejecutar antes de habilitar SUPABASE_CONTEXT_ENABLED.
-- No modifica políticas, credenciales ni registros históricos.
begin;
alter table public.rpa_logs add column if not exists campaign_id text;
alter table public.rpa_logs add column if not exists job_id text;
alter table public.rpa_logs add column if not exists role text;
alter table public.rpa_logs add column if not exists http_status integer;
alter table public.rpa_logs add column if not exists recovery text;
commit;
