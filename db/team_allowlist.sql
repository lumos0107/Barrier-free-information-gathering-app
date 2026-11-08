-- 팀 허용 목록. 로그인한 계정 가운데 이 표에 있는 계정만 기록을 읽고 더한다.
-- 외부 가입과 익명 로그인은 꺼져 있다(2026-11-08 확인). 이 파일은 그것이 실수로 켜져도 막는 둘째 울타리다.
-- 표의 행(팀 계정의 user id)은 저장소에 넣지 않는다. SQL 편집기나 CLI에서 따로 넣는다:
--   insert into public.team_members (user_id) select id from auth.users where email in ('...', '...');
create table if not exists public.team_members (
  user_id uuid primary key references auth.users (id) on delete cascade
);

alter table public.team_members enable row level security;
revoke all on public.team_members from anon, authenticated;
-- 정책 안의 하위 조회는 부른 계정의 권한으로 돈다. 자기 행만 보이게 읽기를 연다.
grant select on public.team_members to authenticated;
drop policy if exists self_read on public.team_members;
create policy self_read on public.team_members
  for select to authenticated using (user_id = auth.uid());

-- 기록 표에 넣을 수 있는 칸을 줄인다. user_id와 received_at은 서버가 채운다.
revoke insert on public.field_records from authenticated;
grant insert (id, run_id, kind, payload, device_id, app_version, recorded_at) on public.field_records to authenticated;

drop policy if exists team_read on public.field_records;
drop policy if exists team_insert on public.field_records;

create policy team_read on public.field_records
  for select to authenticated
  using (exists (select 1 from public.team_members m where m.user_id = auth.uid()));

create policy team_insert on public.field_records
  for insert to authenticated
  with check (user_id = auth.uid() and exists (select 1 from public.team_members m where m.user_id = auth.uid()));
