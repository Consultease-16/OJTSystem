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

-- Active partnered companies (MOA tracking)
create table if not exists company_partnered (
  id uuid primary key default gen_random_uuid(),
  checklist_row_id uuid not null unique references company_checklist(id) on delete cascade,
  company_name text not null default '',
  moa_start_date date not null,
  moa_expiration_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists company_partnered_moa_start_date_idx
  on company_partnered (moa_start_date);

create or replace function set_company_partnered_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists company_partnered_updated_at_trg on company_partnered;
create trigger company_partnered_updated_at_trg
before update on company_partnered
for each row
execute function set_company_partnered_updated_at();

-- Optional one-time backfill for already notarized checklist rows
insert into company_partnered (checklist_row_id, company_name, moa_start_date)
select
  cc.id,
  cc.company_name,
  cc.processed_notarized_passed_at::date
from company_checklist cc
where cc.processed_notarized_checked = true
  and cc.processed_notarized_passed_at is not null
on conflict (checklist_row_id)
do update set
  company_name = excluded.company_name,
  moa_start_date = excluded.moa_start_date;
