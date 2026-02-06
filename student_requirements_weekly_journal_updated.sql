-- Combined update script:
-- 1) Student requirements (with Start of OJT)
-- 2) Weekly Journal + Submission Schedule

create extension if not exists pgcrypto;

-- Student Requirements
create table if not exists student_requirements (
  id uuid primary key default gen_random_uuid(),
  student_id uuid references students(id) on delete cascade,
  last_name text not null,
  first_name text not null,
  second_name text,
  middle_initial text,
  start_of_ojt date,
  student_no text not null,
  section text not null,
  program text not null,
  school_year text check (school_year ~ '^[0-9]{4} - [0-9]{4}$'),
  practicum_application boolean not null default false,
  letter_of_intent boolean not null default false,
  endorsement_letter boolean not null default false,
  practicum_parental_consent boolean not null default false,
  acceptance_form boolean not null default false,
  reply_form boolean not null default false,
  practicum_training_agreement boolean not null default false,
  attendance_sheet boolean not null default false,
  weekly_journal boolean not null default false,
  transmittal_form boolean not null default false,
  evaluation_form boolean not null default false,
  outreach_program_design boolean not null default false,
  outreach_post_activity_report boolean not null default false,
  ojt_log_sheet boolean not null default false,
  requirements_checklist boolean not null default false,
  cca_hymn boolean not null default false
);

create index if not exists student_requirements_student_id_idx on student_requirements (student_id);
create index if not exists student_requirements_student_no_idx on student_requirements (student_no);

alter table student_requirements
  add column if not exists start_of_ojt date;

-- Remove old DTR month-hour columns from student_requirements
-- (DTR is handled in separate table: attendance_sheet_dtr)
alter table student_requirements drop column if exists dtr_january_hours;
alter table student_requirements drop column if exists dtr_february_hours;
alter table student_requirements drop column if exists dtr_march_hours;
alter table student_requirements drop column if exists dtr_april_hours;
alter table student_requirements drop column if exists dtr_may_hours;
alter table student_requirements drop column if exists dtr_june_hours;

-- Ensure attendance_sheet exists for existing DBs
alter table student_requirements
  add column if not exists attendance_sheet boolean not null default false;

create unique index if not exists student_requirements_student_id_uidx on student_requirements (student_id);

create or replace function sync_student_requirements()
returns void
language plpgsql
as $$
begin
  insert into student_requirements (
    student_id,
    last_name,
    first_name,
    second_name,
    middle_initial,
    student_no,
    section,
    program,
    school_year
  )
  select
    s.id,
    s.last_name,
    s.first_name,
    s.second_name,
    s.middle_initial,
    s.student_no,
    s.section,
    s.program,
    s.school_year
  from students s
  on conflict (student_id) do update
  set
    last_name = excluded.last_name,
    first_name = excluded.first_name,
    second_name = excluded.second_name,
    middle_initial = excluded.middle_initial,
    student_no = excluded.student_no,
    section = excluded.section,
    program = excluded.program,
    school_year = excluded.school_year;
end;
$$;

create or replace function sync_student_requirements_row()
returns trigger
language plpgsql
as $$
begin
  insert into student_requirements (
    student_id,
    last_name,
    first_name,
    second_name,
    middle_initial,
    student_no,
    section,
    program,
    school_year
  )
  values (
    new.id,
    new.last_name,
    new.first_name,
    new.second_name,
    new.middle_initial,
    new.student_no,
    new.section,
    new.program,
    new.school_year
  )
  on conflict (student_id) do update
  set
    last_name = excluded.last_name,
    first_name = excluded.first_name,
    second_name = excluded.second_name,
    middle_initial = excluded.middle_initial,
    student_no = excluded.student_no,
    section = excluded.section,
    program = excluded.program,
    school_year = excluded.school_year;
  return new;
end;
$$;

drop trigger if exists students_sync_requirements_trg on students;
create trigger students_sync_requirements_trg
after insert or update on students
for each row
execute function sync_student_requirements_row();

-- Weekly Journal + Submission Schedule
create table if not exists submission_schedules (
  id uuid primary key default gen_random_uuid(),
  section text not null unique,
  submission_day smallint not null check (submission_day between 1 and 5),
  created_at timestamptz not null default now()
);

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

create table if not exists weekly_journal_logs (
  id uuid primary key default gen_random_uuid(),
  attendance_id uuid not null references weekly_journal(id) on delete cascade,
  logged_at timestamptz not null default now()
);

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

-- Attendance Sheet (DTR) per student
create table if not exists attendance_sheet_dtr (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null unique references students(id) on delete cascade,
  january_hours int not null default 0 check (january_hours >= 0),
  february_hours int not null default 0 check (february_hours >= 0),
  march_hours int not null default 0 check (march_hours >= 0),
  april_hours int not null default 0 check (april_hours >= 0),
  may_hours int not null default 0 check (may_hours >= 0),
  june_hours int not null default 0 check (june_hours >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists attendance_sheet_dtr_student_idx on attendance_sheet_dtr (student_id);

-- Sync DTR rows for existing/new students (one row per student)
create or replace function sync_attendance_sheet_dtr()
returns void
language plpgsql
as $$
begin
  insert into attendance_sheet_dtr (student_id)
  select s.id
  from students s
  on conflict (student_id) do nothing;
end;
$$;

-- Keep updated_at fresh
create or replace function set_attendance_sheet_dtr_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists attendance_sheet_dtr_updated_at_trg on attendance_sheet_dtr;
create trigger attendance_sheet_dtr_updated_at_trg
before update on attendance_sheet_dtr
for each row
execute function set_attendance_sheet_dtr_updated_at();

-- Auto-create DTR row when student is inserted
create or replace function sync_attendance_sheet_dtr_row()
returns trigger
language plpgsql
as $$
begin
  insert into attendance_sheet_dtr (student_id)
  values (new.id)
  on conflict (student_id) do nothing;
  return new;
end;
$$;

drop trigger if exists students_sync_dtr_trg on students;
create trigger students_sync_dtr_trg
after insert on students
for each row
execute function sync_attendance_sheet_dtr_row();

-- Helper: total completion hours (Jan-Jun) for one student
create or replace function get_dtr_total_hours(p_student_id uuid)
returns int
language sql
stable
as $$
  select
    coalesce(january_hours, 0) +
    coalesce(february_hours, 0) +
    coalesce(march_hours, 0) +
    coalesce(april_hours, 0) +
    coalesce(may_hours, 0) +
    coalesce(june_hours, 0)
  from attendance_sheet_dtr
  where student_id = p_student_id
$$;

-- Helper: completion status based on total hours
create or replace function get_dtr_completion_status(p_student_id uuid)
returns text
language sql
stable
as $$
  select case
    when coalesce(get_dtr_total_hours(p_student_id), 0) >= 500 then 'OJT Completed'
    else 'In progress'
  end
$$;
