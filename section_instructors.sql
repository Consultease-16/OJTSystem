-- Section list and instructor assignment
create extension if not exists pgcrypto;

create table if not exists section_list (
  id uuid primary key default gen_random_uuid(),
  section text not null,
  school_year text not null,
  created_at timestamptz not null default now(),
  unique (section, school_year)
);

create table if not exists section_instructors (
  id uuid primary key default gen_random_uuid(),
  section_id uuid not null references section_list(id) on delete cascade,
  instructor_id uuid references practicum_instructors(id) on delete cascade,
  coordinator_id uuid references practicum_coordinators(id) on delete cascade,
  assigned_at timestamptz not null default now(),
  unique (section_id)
);

create index if not exists section_instructors_section_id_idx on section_instructors (section_id);
create index if not exists section_instructors_instructor_id_idx on section_instructors (instructor_id);
create index if not exists section_instructors_coordinator_id_idx on section_instructors (coordinator_id);

create or replace function sync_section_list_from_student_requirements()
returns void
language plpgsql
as $$
begin
  insert into section_list (section, school_year)
  select distinct sr.section, sr.school_year
  from student_requirements sr
  where sr.section is not null and sr.section <> ''
    and sr.school_year is not null and sr.school_year <> ''
  on conflict (section, school_year) do nothing;
end;
$$;

create or replace function sync_section_list_from_student_requirements_row()
returns trigger
language plpgsql
as $$
begin
  -- Keep section_list in sync for new/current values.
  if tg_op in ('INSERT', 'UPDATE')
     and new.section is not null and new.section <> ''
     and new.school_year is not null and new.school_year <> '' then
    insert into section_list (section, school_year)
    values (new.section, new.school_year)
    on conflict (section, school_year) do nothing;
  end if;

  -- Cleanup old keys when no student_requirements row references them anymore.
  if tg_op in ('UPDATE', 'DELETE')
     and old.section is not null and old.section <> ''
     and old.school_year is not null and old.school_year <> '' then
    if not exists (
      select 1
      from student_requirements sr
      where sr.section = old.section
        and sr.school_year = old.school_year
    ) then
      delete from section_list sl
      where sl.section = old.section
        and sl.school_year = old.school_year
        and not exists (
          select 1
          from section_instructors si
          where si.section_id = sl.id
        );
    end if;
  end if;

  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

drop trigger if exists student_requirements_sync_section_list_trg on student_requirements;
create trigger student_requirements_sync_section_list_trg
after insert or update of section, school_year or delete on student_requirements
for each row
execute function sync_section_list_from_student_requirements_row();

-- Backfill section_list immediately after installing this script.
select sync_section_list_from_student_requirements();

-- Read-only view for assignment + student requirement overview.
create or replace view v_section_assignment_requirements as
select
  sl.id as section_id,
  sl.section,
  sl.school_year,
  si.instructor_id,
  si.coordinator_id,
  sr.student_id,
  sr.student_no,
  sr.last_name,
  sr.first_name,
  sr.second_name,
  sr.middle_initial,
  sr.program,
  sr.practicum_application,
  sr.letter_of_intent,
  sr.endorsement_letter,
  sr.practicum_parental_consent,
  sr.acceptance_form,
  sr.reply_form,
  sr.practicum_training_agreement,
  sr.attendance_sheet,
  sr.weekly_journal,
  sr.transmittal_form,
  sr.evaluation_form,
  sr.outreach_program_design,
  sr.outreach_post_activity_report,
  sr.ojt_log_sheet,
  sr.requirements_checklist,
  sr.cca_hymn
from section_list sl
left join section_instructors si on si.section_id = sl.id
left join student_requirements sr
  on sr.section = sl.section and sr.school_year = sl.school_year;
