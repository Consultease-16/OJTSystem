-- Weekly Journal + Submission Schedule
create extension if not exists pgcrypto;

-- Submission schedule per section (Mon=1 ... Fri=5)
create table if not exists submission_schedules (
  id uuid primary key default gen_random_uuid(),
  section text not null unique,
  submission_day smallint not null check (submission_day between 1 and 5),
  created_at timestamptz not null default now()
);

-- Monthly attendance rows (one row per student, per week occurrence)
create table if not exists weekly_journal (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id) on delete cascade,
  section text not null,
  year int not null,
  month smallint not null check (month between 1 and 12),
  week_no smallint not null check (week_no between 1 and 5),
  submission_day smallint not null check (submission_day between 1 and 5),
  due_date date not null,
  submitted_at timestamptz,
  status text check (status in ('on_time', 'late', 'late_excused')),
  status_override boolean not null default false,
  status_note text,
  unique (student_id, year, month, week_no)
);

create index if not exists weekly_journal_student_idx on weekly_journal (student_id);
create index if not exists weekly_journal_section_idx on weekly_journal (section);
create index if not exists weekly_journal_due_idx on weekly_journal (due_date);

-- Ensure new override columns exist for existing DBs
alter table weekly_journal
  add column if not exists status_override boolean not null default false;

alter table weekly_journal
  add column if not exists status_note text;

do $$
begin
  if exists (
    select 1 from pg_constraint
    where conname = 'weekly_journal_status_check'
      and conrelid = 'weekly_journal'::regclass
  ) then
    alter table weekly_journal drop constraint weekly_journal_status_check;
  end if;
end $$;

alter table weekly_journal
  add constraint weekly_journal_status_check
  check (status in ('on_time', 'late', 'late_excused') or status is null);

-- Log each checkbox click
create table if not exists weekly_journal_logs (
  id uuid primary key default gen_random_uuid(),
  attendance_id uuid not null references weekly_journal(id) on delete cascade,
  logged_at timestamptz not null default now()
);

-- Helper: compute the due date for a given week in a month for a given weekday (Mon=1..Fri=5)
create or replace function get_due_date_for_week(
  p_year int,
  p_month int,
  p_submission_day int,
  p_week_no int
)
returns date
language plpgsql
as $$
declare
  result date;
begin
  select d into result
  from (
    select (date_trunc('month', make_date(p_year, p_month, 1)) + (n || ' days')::interval)::date as d
    from generate_series(0, 40) as n
  ) days
  where extract(isodow from d) = p_submission_day
    and extract(month from d) = p_month
  order by d
  offset (p_week_no - 1) limit 1;

  return result;
end;
$$;

-- Trigger: set due_date and status on insert/update
create or replace function set_weekly_journal_status()
returns trigger
language plpgsql
as $$
begin
  if new.due_date is null then
    new.due_date := get_due_date_for_week(new.year, new.month, new.submission_day, new.week_no);
  end if;

  if new.submitted_at is not null then
    if coalesce(new.status_override, false) = false then
      if (new.submitted_at::date > new.due_date) then
        new.status := 'late';
      else
        new.status := 'on_time';
      end if;
    end if;
  else
    new.status := null;
    new.status_override := false;
    new.status_note := null;
  end if;

  return new;
end;
$$;

drop trigger if exists weekly_journal_status_trg on weekly_journal;
create trigger weekly_journal_status_trg
before insert or update on weekly_journal
for each row
execute function set_weekly_journal_status();

-- Sync rows for Jan-Jun of a given year based on submission schedules
create or replace function sync_weekly_journal(p_year int)
returns void
language plpgsql
as $$
begin
  insert into weekly_journal (
    student_id,
    section,
    year,
    month,
    week_no,
    submission_day,
    due_date
  )
  select
    s.id,
    s.section,
    p_year,
    m.month,
    w.week_no,
    sch.submission_day,
    get_due_date_for_week(p_year, m.month, sch.submission_day, w.week_no)
  from students s
  join submission_schedules sch on sch.section = s.section
  cross join (select generate_series(1, 6) as month) m
  cross join (select generate_series(1, 5) as week_no) w
  where get_due_date_for_week(p_year, m.month, sch.submission_day, w.week_no) is not null
  on conflict do nothing;
end;
$$;

-- Sync rows for a single section (updates existing rows when schedule changes)
create or replace function sync_weekly_journal_for_section(p_year int, p_section text)
returns void
language plpgsql
as $$
declare
  v_day int;
begin
  select submission_day into v_day
  from submission_schedules
  where section = p_section;

  if v_day is null then
    return;
  end if;

  with calc as (
    select
      w.id,
      get_due_date_for_week(w.year, w.month, v_day, w.week_no) as new_due
    from weekly_journal w
    where w.section = p_section and w.year = p_year
  )
  update weekly_journal w
  set submission_day = v_day,
      due_date = calc.new_due
  from calc
  where w.id = calc.id and calc.new_due is not null;

  delete from weekly_journal w
  where w.section = p_section
    and w.year = p_year
    and get_due_date_for_week(w.year, w.month, v_day, w.week_no) is null;

  insert into weekly_journal (
    student_id,
    section,
    year,
    month,
    week_no,
    submission_day,
    due_date
  )
  select
    s.id,
    s.section,
    p_year,
    m.month,
    w.week_no,
    v_day,
    get_due_date_for_week(p_year, m.month, v_day, w.week_no)
  from students s
  cross join (select generate_series(1, 6) as month) m
  cross join (select generate_series(1, 5) as week_no) w
  where s.section = p_section
    and get_due_date_for_week(p_year, m.month, v_day, w.week_no) is not null
  on conflict do nothing;
end;
$$;

-- Log checkbox clicks
create or replace function log_weekly_journal()
returns trigger
language plpgsql
as $$
begin
  if new.submitted_at is not null and (old.submitted_at is null or new.submitted_at <> old.submitted_at) then
    insert into weekly_journal_logs (attendance_id) values (new.id);
  end if;
  return new;
end;
$$;

drop trigger if exists weekly_journal_log_trg on weekly_journal;
create trigger weekly_journal_log_trg
after update on weekly_journal
for each row
execute function log_weekly_journal();
