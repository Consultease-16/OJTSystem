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

-- Ensure start_of_ojt exists for existing DBs
alter table student_requirements
  add column if not exists start_of_ojt date;

-- Ensure attendance_sheet exists for existing DBs
alter table student_requirements
  add column if not exists attendance_sheet boolean not null default false;

-- Move DTR hours out of student_requirements (separate table)
alter table student_requirements drop column if exists dtr_january_hours;
alter table student_requirements drop column if exists dtr_february_hours;
alter table student_requirements drop column if exists dtr_march_hours;
alter table student_requirements drop column if exists dtr_april_hours;
alter table student_requirements drop column if exists dtr_may_hours;
alter table student_requirements drop column if exists dtr_june_hours;

-- Prevent duplicate rows per student
create unique index if not exists student_requirements_student_id_uidx on student_requirements (student_id);

-- Sync from students table without duplicating
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

-- Auto-sync on students insert/update
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

-- Attendance Sheet (DTR) per student (separate from student_requirements)
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
