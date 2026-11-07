-- 현장 측정 기록 표. 폰에 먼저 저장한 기록의 사본을 받는다.
-- 팀 계정은 읽기와 추가만 할 수 있다. 고칠 때는 새 행을 더해 원값을 남긴다.
create table public.field_records (
  id          uuid primary key,
  run_id      text not null,
  kind        text not null,
  payload     jsonb not null,
  device_id   text not null,
  app_version text not null,
  recorded_at timestamptz not null,
  received_at timestamptz not null default now(),
  user_id     uuid not null default auth.uid()
);

alter table public.field_records enable row level security;

revoke all on public.field_records from anon, authenticated;
grant select, insert on public.field_records to authenticated;

create policy team_read on public.field_records
  for select to authenticated using (true);

create policy team_insert on public.field_records
  for insert to authenticated with check (user_id = auth.uid());
