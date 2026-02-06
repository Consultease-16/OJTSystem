-- Company Checklist schema
create extension if not exists pgcrypto;

create table if not exists company_checklist (
  id uuid primary key default gen_random_uuid(),
  company_name text not null default '',

  city_resolution_checked boolean not null default false,
  city_resolution_passed_at timestamptz,
  city_resolution_status text
    check (city_resolution_status in ('pending', 'approved') or city_resolution_status is null),
  city_resolution_returned_at timestamptz,

  company_signing_checked boolean not null default false,
  company_signing_passed_at timestamptz,

  office_president_checked boolean not null default false,
  office_president_passed_at timestamptz,

  processed_notarized_checked boolean not null default false,
  processed_notarized_passed_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists company_checklist_created_at_idx
  on company_checklist (created_at);

create or replace function set_company_checklist_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists company_checklist_updated_at_trg on company_checklist;
create trigger company_checklist_updated_at_trg
before update on company_checklist
for each row
execute function set_company_checklist_updated_at();
