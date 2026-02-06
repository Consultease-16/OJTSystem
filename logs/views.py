import secrets
import datetime
import json
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.db import IntegrityError
import os
import uuid
import urllib.request
import urllib.error
from django.db import connection
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import PracticumCoordinator, PracticumInstructor, Student

def _attach_logo(message):
    logo_path = Path(settings.BASE_DIR) / "ICSLIS LOGO.png"
    if not logo_path.exists():
        return
    img = MIMEImage(logo_path.read_bytes())
    img.add_header("Content-ID", "<icslis-logo>")
    img.add_header("Content-Disposition", "inline", filename="icslis-logo.png")
    message.attach(img)

@never_cache
def front_page(request):
    context = {}
    flash = request.session.pop("flash_message", None)
    flash_type = request.session.pop("flash_message_type", None)
    if flash:
        context["message"] = flash
        context["message_type"] = flash_type or "error"
    if request.method == "POST":
        email = request.POST.get("cca_email") or request.POST.get("username")
        password = request.POST.get("password", "")
        if not email or not password:
            context["message"] = "Please enter your email and password."
            context["message_type"] = "error"
            return render(request, "auth/login.html", context)

        email = email.lower()
        account = Student.objects.filter(cca_email=email).first()
        account_type = "student"
        if not account:
            account = PracticumCoordinator.objects.filter(cca_email=email).first()
            account_type = "coordinator"
        if not account:
            account = PracticumInstructor.objects.filter(cca_email=email).first()
            account_type = "instructor"
        if not account:
            context["message"] = "Invalid login credentials."
            context["message_type"] = "error"
            return render(request, "auth/login.html", context)

        if not account.active_status:
            context["message"] = "Account is not activated yet."
            context["message_type"] = "error"
            return render(request, "auth/login.html", context)

        if not check_password(password, account.password):
            context["message"] = "Invalid login credentials."
            context["message_type"] = "error"
            return render(request, "auth/login.html", context)

        request.session["account_id"] = str(account.id)
        request.session["account_type"] = account_type
        if account.is_password_temp:
            return redirect("change_temp_password")

        if account_type == "student":
            return redirect("student_home")
        return redirect("staff_home")

    return render(request, "auth/login.html", context)


def forgot_password(request):
    context = {}
    if request.method == "POST":
        email = request.POST.get("reset_email", "").strip().lower()
        stage = request.POST.get("stage", "send")

        if not email:
            context["message"] = "Please enter your email."
            context["message_type"] = "error"
            return render(request, "logs/forgot_password.html", context)

        account = Student.objects.filter(cca_email=email).first()
        account_type = "student"
        if not account:
            account = PracticumCoordinator.objects.filter(cca_email=email).first()
            account_type = "coordinator"
        if not account:
            account = PracticumInstructor.objects.filter(cca_email=email).first()
            account_type = "instructor"
        if not account:
            context["message"] = "Email not found. Please contact the admin."
            context["message_type"] = "error"
            return render(request, "logs/forgot_password.html", context)

        if stage in {"send", "resend"}:
            last_key = f"recovery_last_sent:{email}"
            last_sent = request.session.get(last_key)
            if last_sent:
                elapsed = (timezone.now() - timezone.datetime.fromisoformat(last_sent)).total_seconds()
                if elapsed < 60:
                    context["message"] = "Please wait before resending the code."
                    context["message_type"] = "error"
                    context["show_code"] = True
                    context["email"] = email
                    context["cooldown_seconds"] = int(60 - elapsed)
                    return render(request, "logs/forgot_password.html", context)

            code = f"{secrets.randbelow(10**6):06d}"
            account.recovery_code = code
            account.save(update_fields=["recovery_code"])

            subject = "ICSLIS OJT System Password Reset Code"
            text_body = f"Your password reset code is: {code}"
            html_body = render_to_string(
                "emails/recovery_code.html",
                {"recovery_code": code, "email": email},
            )
            msg = EmailMultiAlternatives(subject, text_body, None, [email])
            msg.attach_alternative(html_body, "text/html")
            _attach_logo(msg)
            msg.send()

            context["message"] = "Reset code sent. Please check your email."
            context["message_type"] = "success"
            context["show_code"] = True
            context["email"] = email
            context["cooldown_seconds"] = 60
            request.session[last_key] = timezone.now().isoformat()
            return render(request, "logs/forgot_password.html", context)

        if stage == "verify":
            code = request.POST.get("recovery_code", "").strip()
            if not code:
                context["message"] = "Please enter the reset code."
                context["message_type"] = "error"
                context["show_code"] = True
                context["email"] = email
                return render(request, "logs/forgot_password.html", context)

            if account.recovery_code != code:
                context["message"] = "Invalid reset code."
                context["message_type"] = "error"
                context["show_code"] = True
                context["email"] = email
                return render(request, "logs/forgot_password.html", context)

            request.session[f"recovery_verified:{email}"] = True
            context["show_password"] = True
            context["email"] = email
            return render(request, "logs/forgot_password.html", context)

        if stage == "reset":
            if not request.session.get(f"recovery_verified:{email}"):
                context["message"] = "Please verify your reset code first."
                context["message_type"] = "error"
                context["show_code"] = True
                context["email"] = email
                return render(request, "logs/forgot_password.html", context)

            new_password = request.POST.get("new_password", "")
            confirm_password = request.POST.get("confirm_password", "")
            if not new_password or not confirm_password:
                context["message"] = "Please fill in both password fields."
                context["message_type"] = "error"
                context["show_password"] = True
                context["email"] = email
                return render(request, "logs/forgot_password.html", context)

            if new_password != confirm_password:
                context["message"] = "Passwords do not match."
                context["message_type"] = "error"
                context["show_password"] = True
                context["email"] = email
                return render(request, "logs/forgot_password.html", context)

            account.password = make_password(new_password)
            account.is_password_temp = False
            account.recovery_code = None
            account.save(update_fields=["password", "is_password_temp", "recovery_code"])
            request.session.pop(f"recovery_verified:{email}", None)
            request.session["flash_message"] = "Password reset successful. You can now sign in."
            request.session["flash_message_type"] = "success"
            return redirect("front_page")

    return render(request, "logs/forgot_password.html", context)


def activate_account(request):
    context = {}
    if request.method == "POST":
        email = request.POST.get("cca_email", "").strip().lower()
        stage = request.POST.get("stage", "send")

        if not email:
            context["message"] = "Please enter your CCA email."
            context["message_type"] = "error"
            return render(request, "auth/activation.html", context)

        if stage in {"send", "resend"}:
            last_key = f"activation_last_sent:{email}"
            last_sent = request.session.get(last_key)
            if last_sent:
                elapsed = (timezone.now() - timezone.datetime.fromisoformat(last_sent)).total_seconds()
                if elapsed < 60:
                    context["message"] = "Please wait before resending the code."
                    context["message_type"] = "error"
                    context["show_code"] = True
                    context["email"] = email
                    context["cooldown_seconds"] = int(60 - elapsed)
                    return render(request, "auth/activation.html", context)

            code = f"{secrets.randbelow(10**6):06d}"
            updated = Student.objects.filter(cca_email=email).update(
                activation_code=code,
                active_status=False,
                is_password_temp=True,
            )
            if not updated:
                updated = PracticumCoordinator.objects.filter(cca_email=email).update(
                    activation_code=code,
                    active_status=False,
                    is_password_temp=True,
                )
            if not updated:
                updated = PracticumInstructor.objects.filter(cca_email=email).update(
                    activation_code=code,
                    active_status=False,
                    is_password_temp=True,
                )
            if not updated:
                context["message"] = "Email not found. Please contact the admin."
                context["message_type"] = "error"
            else:
                subject = "ICSLIS OJT System Activation Code"
                text_body = f"Your activation code is: {code}"
                html_body = render_to_string(
                    "emails/activation_code.html",
                    {"activation_code": code, "email": email},
                )
                msg = EmailMultiAlternatives(subject, text_body, None, [email])
                msg.attach_alternative(html_body, "text/html")
                _attach_logo(msg)
                msg.send()
                context["message"] = "Activation code sent. Please check your email."
                context["message_type"] = "success"
                context["show_code"] = True
                context["email"] = email
                context["cooldown_seconds"] = 60
                request.session[last_key] = timezone.now().isoformat()
            return render(request, "auth/activation.html", context)

        code = request.POST.get("activation_code", "").strip()
        if not code:
            context["message"] = "Please enter the activation code."
            context["message_type"] = "error"
            context["show_code"] = True
            context["email"] = email
            return render(request, "auth/activation.html", context)

        temp_password = secrets.token_urlsafe(6)
        hashed_password = make_password(temp_password)
        updated = Student.objects.filter(
            cca_email=email, activation_code=code
        ).update(
            active_status=True,
            password=hashed_password,
            is_password_temp=True,
        )
        if not updated:
            updated = PracticumCoordinator.objects.filter(
                cca_email=email, activation_code=code
            ).update(
                active_status=True,
                password=hashed_password,
                is_password_temp=True,
            )
        if not updated:
            updated = PracticumInstructor.objects.filter(
                cca_email=email, activation_code=code
            ).update(
                active_status=True,
                password=hashed_password,
                is_password_temp=True,
            )

        if updated:
            subject = "ICSLIS OJT System Temporary Password"
            text_body = (
                "Your account is now active.\n"
                f"Temporary password: {temp_password}\n"
                "Please log in and change your password immediately."
            )
            html_body = render_to_string(
                "emails/temp_password.html",
                {"temp_password": temp_password, "email": email},
            )
            msg = EmailMultiAlternatives(subject, text_body, None, [email])
            msg.attach_alternative(html_body, "text/html")
            _attach_logo(msg)
            msg.send()
            request.session["flash_message"] = "Account activated. Temporary password sent to your email."
            request.session["flash_message_type"] = "success"
            return redirect("front_page")
        else:
            context["message"] = "Invalid activation code."
            context["message_type"] = "error"
            context["show_code"] = True
            context["email"] = email

    return render(request, "auth/activation.html", context)


@never_cache
def change_temp_password(request):
    account_id = request.session.get("account_id")
    if not account_id:
        return redirect("front_page")

    account_type = request.session.get("account_type", "student")
    model = Student if account_type == "student" else None
    if account_type == "coordinator":
        model = PracticumCoordinator
    elif account_type == "instructor":
        model = PracticumInstructor

    if model is None:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    context = {"email": account.cca_email}
    if request.method == "POST":
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not new_password or not confirm_password:
            context["message"] = "Please fill in both password fields."
            context["message_type"] = "error"
            return render(request, "auth/change_temp_password.html", context)

        if new_password != confirm_password:
            context["message"] = "Passwords do not match."
            context["message_type"] = "error"
            return render(request, "auth/change_temp_password.html", context)

        account.password = make_password(new_password)
        account.is_password_temp = False
        account.save(update_fields=["password", "is_password_temp"])
        context["message"] = "Password updated. You can now sign in."
        context["message_type"] = "success"
        return render(request, "auth/login.html", context)

    return render(request, "auth/change_temp_password.html", context)


@never_cache
def student_home(request):
    account_id = request.session.get("account_id")
    if not account_id:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    account = Student.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    response = render(request, "student/student_home.html", {"student": account})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@never_cache
def staff_home(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    response = render(request, "staff/staff_home.html", {"account": account, "role": account_type})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@never_cache
def manage_records(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    message = request.session.pop("flash_message", None)
    message_type = request.session.pop("flash_message_type", None)
    search = request.GET.get("q", "").strip()
    program = request.GET.get("program", "").strip()
    school_year = request.GET.get("school_year", "").strip()

    where_clauses = []
    params = []

    if search:
        where_clauses.append(
            "(lower(last_name) like lower(%s) or lower(first_name) like lower(%s) or lower(student_no) like lower(%s))"
        )
        like = f"%{search}%"
        params.extend([like, like, like])

    if program:
        where_clauses.append("(lower(program) like lower(%s) or lower(section) like lower(%s))")
        like = f"%{program}%"
        params.extend([like, like])

    if school_year:
        where_clauses.append("school_year = %s")
        params.append(school_year)

    where_sql = ""
    if where_clauses:
        where_sql = "where " + " and ".join(where_clauses)

    with connection.cursor() as cursor:
        # Keep schema backward-compatible for DBs that have not run the latest SQL yet.
        cursor.execute("alter table student_requirements add column if not exists start_of_ojt date")
        cursor.execute(
            "alter table student_requirements add column if not exists attendance_sheet boolean not null default false"
        )
        cursor.execute(
            """
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
            )
            """
        )
        cursor.execute(
            f"""
            select
              sr.student_id,
              sr.last_name,
              sr.first_name,
              sr.middle_initial,
              sr.start_of_ojt,
              coalesce(dtr.january_hours, 0) as dtr_january_hours,
              coalesce(dtr.february_hours, 0) as dtr_february_hours,
              coalesce(dtr.march_hours, 0) as dtr_march_hours,
              coalesce(dtr.april_hours, 0) as dtr_april_hours,
              coalesce(dtr.may_hours, 0) as dtr_may_hours,
              coalesce(dtr.june_hours, 0) as dtr_june_hours,
              sr.student_no,
              sr.section,
              sr.program,
              sr.school_year,
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
            from student_requirements sr
            left join attendance_sheet_dtr dtr on dtr.student_id = sr.student_id
            {where_sql}
            order by sr.last_name, sr.first_name
            """,
            params,
        )
        columns = [col[0] for col in cursor.description]
        requirements = [dict(zip(columns, row)) for row in cursor.fetchall()]
    response = render(
        request,
        "staff/manage_records.html",
        {
            "account": account,
            "role": account_type,
            "message": message,
            "message_type": message_type,
            "requirements": requirements,
            "filters": {"q": search, "program": program, "school_year": school_year},
        },
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@never_cache
def company_checklist(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    _ensure_company_checklist_table()

    response = render(
        request,
        "staff/company_checklist.html",
        {"account": account, "role": account_type},
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _ensure_company_checklist_table():
    with connection.cursor() as cursor:
        cursor.execute(
            """
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
            )
            """
        )
        cursor.execute(
            """
            create index if not exists company_checklist_created_at_idx
              on company_checklist (created_at)
            """
        )
        cursor.execute(
            """
            create or replace function set_company_checklist_updated_at()
            returns trigger
            language plpgsql
            as $$
            begin
              new.updated_at := now();
              return new;
            end;
            $$;
            """
        )
        cursor.execute("drop trigger if exists company_checklist_updated_at_trg on company_checklist")
        cursor.execute(
            """
            create trigger company_checklist_updated_at_trg
            before update on company_checklist
            for each row
            execute function set_company_checklist_updated_at()
            """
        )


def _serialize_company_checklist_row(row):
    return {
        "id": str(row[0]),
        "companyName": row[1] or "",
        "cityResolution": {
            "checked": bool(row[2]),
            "passedAt": row[3].isoformat() if row[3] else "",
            "approval": row[4] or "",
            "returnedIn": row[5].isoformat() if row[5] else "",
        },
        "companySigning": {
            "checked": bool(row[6]),
            "passedAt": row[7].isoformat() if row[7] else "",
        },
        "officePresident": {
            "checked": bool(row[8]),
            "passedAt": row[9].isoformat() if row[9] else "",
        },
        "processedNotarized": {
            "checked": bool(row[10]),
            "passedAt": row[11].isoformat() if row[11] else "",
        },
    }


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


@never_cache
def company_checklist_data(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        return JsonResponse({"ok": False, "message": "Unauthorized."}, status=401)

    _ensure_company_checklist_table()

    if request.method == "GET":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  id,
                  company_name,
                  city_resolution_checked,
                  city_resolution_passed_at,
                  city_resolution_status,
                  city_resolution_returned_at,
                  company_signing_checked,
                  company_signing_passed_at,
                  office_president_checked,
                  office_president_passed_at,
                  processed_notarized_checked,
                  processed_notarized_passed_at
                from company_checklist
                order by created_at asc
                """
            )
            rows = cursor.fetchall()
        return JsonResponse(
            {
                "ok": True,
                "rows": [_serialize_company_checklist_row(row) for row in rows],
            }
        )

    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "message": "Invalid JSON body."}, status=400)

    action = payload.get("action")
    if action == "add":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into company_checklist (company_name)
                values ('')
                returning
                  id,
                  company_name,
                  city_resolution_checked,
                  city_resolution_passed_at,
                  city_resolution_status,
                  city_resolution_returned_at,
                  company_signing_checked,
                  company_signing_passed_at,
                  office_president_checked,
                  office_president_passed_at,
                  processed_notarized_checked,
                  processed_notarized_passed_at
                """
            )
            row = cursor.fetchone()
        return JsonResponse({"ok": True, "row": _serialize_company_checklist_row(row)})

    if action == "delete":
        row_id = payload.get("row_id")
        if not row_id:
            return JsonResponse({"ok": False, "message": "Missing row_id."}, status=400)
        with connection.cursor() as cursor:
            cursor.execute("delete from company_checklist where id = %s", [row_id])
        return JsonResponse({"ok": True})

    if action == "update":
        row_id = payload.get("row_id")
        row = payload.get("row") or {}
        if not row_id:
            return JsonResponse({"ok": False, "message": "Missing row_id."}, status=400)

        city = row.get("cityResolution") or {}
        signing = row.get("companySigning") or {}
        office = row.get("officePresident") or {}
        notarized = row.get("processedNotarized") or {}

        city_checked = _to_bool(city.get("checked"))
        city_status = (city.get("approval") or "").strip().lower() if city_checked else ""
        if city_status not in {"pending", "approved"}:
            city_status = ""
        city_passed_at = _parse_iso_datetime(city.get("passedAt")) if city_checked else None
        city_returned_at = (
            _parse_iso_datetime(city.get("returnedIn")) if city_checked and city_status == "approved" else None
        )

        signing_checked = _to_bool(signing.get("checked"))
        signing_passed_at = _parse_iso_datetime(signing.get("passedAt")) if signing_checked else None

        office_checked = _to_bool(office.get("checked"))
        office_passed_at = _parse_iso_datetime(office.get("passedAt")) if office_checked else None

        notarized_checked = _to_bool(notarized.get("checked"))
        notarized_passed_at = _parse_iso_datetime(notarized.get("passedAt")) if notarized_checked else None

        with connection.cursor() as cursor:
            cursor.execute(
                """
                update company_checklist
                set
                  company_name = %s,
                  city_resolution_checked = %s,
                  city_resolution_passed_at = %s,
                  city_resolution_status = %s,
                  city_resolution_returned_at = %s,
                  company_signing_checked = %s,
                  company_signing_passed_at = %s,
                  office_president_checked = %s,
                  office_president_passed_at = %s,
                  processed_notarized_checked = %s,
                  processed_notarized_passed_at = %s
                where id = %s
                returning
                  id,
                  company_name,
                  city_resolution_checked,
                  city_resolution_passed_at,
                  city_resolution_status,
                  city_resolution_returned_at,
                  company_signing_checked,
                  company_signing_passed_at,
                  office_president_checked,
                  office_president_passed_at,
                  processed_notarized_checked,
                  processed_notarized_passed_at
                """,
                [
                    (row.get("companyName") or "").strip(),
                    city_checked,
                    city_passed_at,
                    city_status or None,
                    city_returned_at,
                    signing_checked,
                    signing_passed_at,
                    office_checked,
                    office_passed_at,
                    notarized_checked,
                    notarized_passed_at,
                    row_id,
                ],
            )
            updated = cursor.fetchone()
        if not updated:
            return JsonResponse({"ok": False, "message": "Checklist row not found."}, status=404)
        return JsonResponse({"ok": True, "row": _serialize_company_checklist_row(updated)})

    return JsonResponse({"ok": False, "message": "Unknown action."}, status=400)


@never_cache
def sync_student_requirements_view(request):
    if request.method != "POST":
        return redirect("manage_records")

    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    with connection.cursor() as cursor:
        cursor.execute("select sync_student_requirements();")
        cursor.execute("select sync_attendance_sheet_dtr();")
        cursor.execute("select sync_weekly_journal(%s);", [timezone.now().year])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "message": "Student details have been synced."})

    request.session["flash_message"] = "Student details have been synced."
    request.session["flash_message_type"] = "success"
    return redirect("manage_records")


@never_cache
def schedules_view(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        return JsonResponse({"ok": False, "message": "Unauthorized."}, status=401)

    if request.method == "GET":
        with connection.cursor() as cursor:
            cursor.execute(
                "select section, submission_day from submission_schedules order by section"
            )
            rows = cursor.fetchall()
        schedules = [{"section": r[0], "submission_day": r[1]} for r in rows]
        return JsonResponse({"ok": True, "schedules": schedules})

    if request.method == "POST":
        action = request.POST.get("action")
        section = (request.POST.get("section") or "").strip()
        submission_day = request.POST.get("submission_day")
        if action == "add":
            if not section or not submission_day:
                return JsonResponse({"ok": False, "message": "Section and day required."}, status=400)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into submission_schedules (section, submission_day)
                    values (%s, %s)
                    on conflict (section)
                    do update set submission_day = excluded.submission_day
                    """,
                    [section, int(submission_day)],
                )
                cursor.execute("select sync_weekly_journal_for_section(%s, %s);", [timezone.now().year, section])
            return JsonResponse({"ok": True})
        if action == "delete":
            if not section:
                return JsonResponse({"ok": False, "message": "Section required."}, status=400)
            with connection.cursor() as cursor:
                cursor.execute("delete from submission_schedules where section = %s", [section])
                cursor.execute("delete from weekly_journal where section = %s and year = %s", [section, timezone.now().year])
            return JsonResponse({"ok": True})

    return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)


@never_cache
def weekly_journal_weeks(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        return JsonResponse({"ok": False, "message": "Unauthorized."}, status=401)

    section = (request.GET.get("section") or "").strip()
    month = request.GET.get("month")
    year = request.GET.get("year")
    if not section or not month or not year:
        return JsonResponse({"ok": False, "message": "Missing parameters."}, status=400)

    with connection.cursor() as cursor:
        cursor.execute("select sync_weekly_journal_for_section(%s, %s);", [int(year), section])
        cursor.execute(
            """
            select id, week_no, due_date, submitted_at, status, submission_day, status_note
            from weekly_journal
            where section = %s and month = %s and year = %s
            order by week_no
            """,
            [section, int(month), int(year)],
        )
        rows = cursor.fetchall()

    weeks = [
        {
            "id": str(r[0]),
            "week_no": r[1],
            "due_date": r[2].isoformat() if r[2] else None,
            "submitted_at": r[3].isoformat() if r[3] else None,
            "status": r[4],
            "submission_day": r[5],
            "status_note": r[6],
        }
        for r in rows
    ]
    return JsonResponse({"ok": True, "weeks": weeks})


@never_cache
def update_weekly_journal_check(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        return JsonResponse({"ok": False, "message": "Unauthorized."}, status=401)

    attendance_id = request.POST.get("attendance_id")
    checked = request.POST.get("checked")
    if not attendance_id or checked is None:
        return JsonResponse({"ok": False, "message": "Missing parameters."}, status=400)

    allowed_statuses = {"late_excused", "late"}
    status_override = request.POST.get("status_override")
    status_note = (request.POST.get("status_note") or "").strip()

    with connection.cursor() as cursor:
        if checked == "true":
            if status_override in allowed_statuses:
                cursor.execute(
                    """
                    update weekly_journal
                    set submitted_at = now(),
                        status = %s,
                        status_override = true,
                        status_note = %s
                    where id = %s
                    """,
                    [status_override, status_note or None, attendance_id],
                )
            else:
                cursor.execute(
                    """
                    update weekly_journal
                    set submitted_at = now(),
                        status = null,
                        status_override = false,
                        status_note = null
                    where id = %s
                    """,
                    [attendance_id],
                )
        else:
            cursor.execute(
                """
                update weekly_journal
                set submitted_at = null,
                    status = null,
                    status_override = false,
                    status_note = null
                where id = %s
                """,
                [attendance_id],
            )
        cursor.execute(
            "select submitted_at, status, status_note from weekly_journal where id = %s",
            [attendance_id],
        )
        row = cursor.fetchone()

    return JsonResponse(
        {
            "ok": True,
            "submitted_at": row[0].isoformat() if row and row[0] else None,
            "status": row[1] if row else None,
            "status_note": row[2] if row else None,
        }
    )


@never_cache
def update_student_requirement(request):
    if request.method != "POST":
        return redirect("manage_records")

    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    student_id = request.POST.get("student_id")
    field = request.POST.get("field")
    value = request.POST.get("value")

    allowed_fields = {
        "practicum_application",
        "letter_of_intent",
        "endorsement_letter",
        "practicum_parental_consent",
        "acceptance_form",
        "reply_form",
        "practicum_training_agreement",
        "attendance_sheet",
        "weekly_journal",
        "transmittal_form",
        "evaluation_form",
        "outreach_program_design",
        "outreach_post_activity_report",
        "ojt_log_sheet",
        "requirements_checklist",
        "cca_hymn",
    }
    date_fields = {"start_of_ojt"}
    hour_fields = {
        "dtr_january_hours",
        "dtr_february_hours",
        "dtr_march_hours",
        "dtr_april_hours",
        "dtr_may_hours",
        "dtr_june_hours",
    }

    if not student_id or (field not in allowed_fields and field not in date_fields and field not in hour_fields):
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": "Invalid update request."}, status=400)
        request.session["flash_message"] = "Invalid update request."
        request.session["flash_message_type"] = "error"
        return redirect("manage_records")

    if field in allowed_fields and value not in {"true", "false"}:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": "Invalid update request."}, status=400)
        request.session["flash_message"] = "Invalid update request."
        request.session["flash_message_type"] = "error"
        return redirect("manage_records")

    if field == "attendance_sheet":
        with connection.cursor() as cursor:
            cursor.execute(
                "alter table student_requirements add column if not exists attendance_sheet boolean not null default false"
            )

    if field in date_fields:
        parsed_date = None
        if value:
            try:
                parsed_date = datetime.datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"ok": False, "message": "Invalid date format."}, status=400)
                request.session["flash_message"] = "Invalid date format."
                request.session["flash_message_type"] = "error"
                return redirect("manage_records")
        with connection.cursor() as cursor:
            cursor.execute(
                "update student_requirements set start_of_ojt = %s where student_id = %s",
                [parsed_date, student_id],
            )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": True,
                    "field": field,
                    "value": parsed_date.isoformat() if parsed_date else "",
                }
            )
        request.session["flash_message"] = "Student requirement updated."
        request.session["flash_message_type"] = "success"
        return redirect("manage_records")

    if field in hour_fields:
        try:
            parsed_hours = int(value)
        except (TypeError, ValueError):
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Hours must be a valid number."}, status=400)
            request.session["flash_message"] = "Hours must be a valid number."
            request.session["flash_message_type"] = "error"
            return redirect("manage_records")
        if parsed_hours < 0:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "message": "Hours cannot be negative."}, status=400)
            request.session["flash_message"] = "Hours cannot be negative."
            request.session["flash_message_type"] = "error"
            return redirect("manage_records")
        with connection.cursor() as cursor:
            month_field_map = {
                "dtr_january_hours": "january_hours",
                "dtr_february_hours": "february_hours",
                "dtr_march_hours": "march_hours",
                "dtr_april_hours": "april_hours",
                "dtr_may_hours": "may_hours",
                "dtr_june_hours": "june_hours",
            }
            target_field = month_field_map[field]
            cursor.execute(
                """
                insert into attendance_sheet_dtr (student_id)
                values (%s)
                on conflict (student_id) do nothing
                """,
                [student_id],
            )
            cursor.execute(
                f"update attendance_sheet_dtr set {target_field} = %s where student_id = %s",
                [parsed_hours, student_id],
            )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "field": field, "value": parsed_hours})
        request.session["flash_message"] = "Student requirement updated."
        request.session["flash_message_type"] = "success"
        return redirect("manage_records")

    with connection.cursor() as cursor:
        cursor.execute(
            f"update student_requirements set {field} = %s where student_id = %s",
            [value == "true", student_id],
        )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "field": field, "value": value == "true"})

    request.session["flash_message"] = "Student requirement updated."
    request.session["flash_message_type"] = "success"
    return redirect("manage_records")


@never_cache
def staff_profile(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    message = request.session.pop("flash_message", None)
    message_type = request.session.pop("flash_message_type", None)
    response = render(
        request,
        "staff/staff_profile.html",
        {"account": account, "role": account_type, "message": message, "message_type": message_type},
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@never_cache
def manage_accounts(request):
    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session.pop("account_id", None)
        request.session.pop("account_type", None)
        return redirect("front_page")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_student":
            try:
                student = Student.objects.create(
                    student_no=request.POST.get("student_no", "").strip(),
                    cca_email=request.POST.get("cca_email", "").strip(),
                    last_name=request.POST.get("last_name", "").strip(),
                    first_name=request.POST.get("first_name", "").strip(),
                    second_name=request.POST.get("second_name") or None,
                    middle_initial=request.POST.get("middle_initial") or None,
                    school_year=request.POST.get("school_year") or None,
                    program=request.POST.get("program", "").strip(),
                    section=request.POST.get("section", "").strip(),
                    password="",
                    activation_code="",
                    recovery_code=None,
                    active_status=False,
                    is_password_temp=True,
                )
            except IntegrityError:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {"ok": False, "message": "Student account already exists (student number or email)."},
                        status=400,
                    )
                request.session["flash_message"] = "Student account already exists (student number or email)."
                request.session["flash_message_type"] = "error"
                return redirect("manage_accounts")
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "ok": True,
                        "mode": "add",
                        "type": "student",
                        "record": {
                            "id": str(student.id),
                            "student_no": student.student_no,
                            "last_name": student.last_name,
                            "first_name": student.first_name,
                            "middle_initial": student.middle_initial,
                            "second_name": student.second_name,
                            "section": student.section,
                            "program": student.program,
                            "cca_email": student.cca_email,
                            "active_status": student.active_status,
                        },
                    }
                )
            request.session["flash_message"] = "Student account added."
            request.session["flash_message_type"] = "success"
            return redirect("manage_accounts")

        if action == "add_instructor":
            try:
                instructor = PracticumInstructor.objects.create(
                    cca_email=request.POST.get("cca_email", "").strip(),
                    last_name=request.POST.get("last_name", "").strip(),
                    first_name=request.POST.get("first_name", "").strip(),
                    second_name=request.POST.get("second_name") or None,
                    middle_initial=request.POST.get("middle_initial") or None,
                    password="",
                    activation_code="",
                    recovery_code=None,
                    active_status=False,
                    is_password_temp=True,
                )
            except IntegrityError:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {"ok": False, "message": "Instructor account already exists (email)."},
                        status=400,
                    )
                request.session["flash_message"] = "Instructor account already exists (email)."
                request.session["flash_message_type"] = "error"
                return redirect("manage_accounts")
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "ok": True,
                        "mode": "add",
                        "type": "instructor",
                        "record": {
                            "id": str(instructor.id),
                            "last_name": instructor.last_name,
                            "first_name": instructor.first_name,
                            "middle_initial": instructor.middle_initial,
                            "second_name": instructor.second_name,
                            "cca_email": instructor.cca_email,
                            "active_status": instructor.active_status,
                        },
                    }
                )
            request.session["flash_message"] = "Instructor account added."
            request.session["flash_message_type"] = "success"
            return redirect("manage_accounts")

        if action == "update_student":
            student_id = request.POST.get("id")
            Student.objects.filter(id=student_id).update(
                student_no=request.POST.get("student_no", "").strip(),
                cca_email=request.POST.get("cca_email", "").strip(),
                last_name=request.POST.get("last_name", "").strip(),
                first_name=request.POST.get("first_name", "").strip(),
                second_name=request.POST.get("second_name") or None,
                middle_initial=request.POST.get("middle_initial") or None,
                program=request.POST.get("program", "").strip(),
                section=request.POST.get("section", "").strip(),
                school_year=request.POST.get("school_year") or None,
            )
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                student = Student.objects.filter(id=student_id).first()
                return JsonResponse(
                    {
                        "ok": True,
                        "mode": "update",
                        "type": "student",
                        "record": {
                            "id": str(student.id),
                            "student_no": student.student_no,
                            "last_name": student.last_name,
                            "first_name": student.first_name,
                            "middle_initial": student.middle_initial,
                            "second_name": student.second_name,
                            "section": student.section,
                            "program": student.program,
                            "cca_email": student.cca_email,
                            "active_status": student.active_status,
                        },
                    }
                )
            request.session["flash_message"] = "Student account updated."
            request.session["flash_message_type"] = "success"
            return redirect("manage_accounts")

        if action == "update_instructor":
            instructor_id = request.POST.get("id")
            PracticumInstructor.objects.filter(id=instructor_id).update(
                cca_email=request.POST.get("cca_email", "").strip(),
                last_name=request.POST.get("last_name", "").strip(),
                first_name=request.POST.get("first_name", "").strip(),
                second_name=request.POST.get("second_name") or None,
                middle_initial=request.POST.get("middle_initial") or None,
            )
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                instructor = PracticumInstructor.objects.filter(id=instructor_id).first()
                return JsonResponse(
                    {
                        "ok": True,
                        "mode": "update",
                        "type": "instructor",
                        "record": {
                            "id": str(instructor.id),
                            "last_name": instructor.last_name,
                            "first_name": instructor.first_name,
                            "middle_initial": instructor.middle_initial,
                            "second_name": instructor.second_name,
                            "cca_email": instructor.cca_email,
                            "active_status": instructor.active_status,
                        },
                    }
                )
            request.session["flash_message"] = "Instructor account updated."
            request.session["flash_message_type"] = "success"
            return redirect("manage_accounts")

    message = request.session.pop("flash_message", None)
    message_type = request.session.pop("flash_message_type", None)
    students = Student.objects.all().order_by("last_name", "first_name")
    instructors = PracticumInstructor.objects.all().order_by("last_name", "first_name")
    edit_type = request.GET.get("edit_type")
    edit_id = request.GET.get("edit_id")
    edit_record = None
    if edit_type == "student" and edit_id:
        edit_record = Student.objects.filter(id=edit_id).first()
    if edit_type == "instructor" and edit_id:
        edit_record = PracticumInstructor.objects.filter(id=edit_id).first()

    response = render(
        request,
        "staff/manage_accounts.html",
        {
            "account": account,
            "role": account_type,
            "message": message,
            "message_type": message_type,
            "students": students,
            "instructors": instructors,
            "edit_type": edit_type,
            "edit_record": edit_record,
        },
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@never_cache
def upload_staff_profile_image(request):
    if request.method != "POST":
        return redirect("staff_profile")

    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    image = request.FILES.get("profile_image")
    if not image:
        request.session["flash_message"] = "Please choose an image to upload."
        request.session["flash_message_type"] = "error"
        return redirect("staff_profile")

    supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
    service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    bucket = (os.getenv("SUPABASE_BUCKET") or "OJTSystemProfile").strip()

    if not supabase_url or not service_role_key or not bucket:
        request.session["flash_message"] = "Supabase configuration is missing."
        request.session["flash_message_type"] = "error"
        return redirect("staff_profile")

    ext = os.path.splitext(image.name)[1].lower()
    safe_ext = ext if ext in {".jpg", ".jpeg", ".png", ".webp"} else ".png"
    object_path = f"staff/{account_type}/{account_id}/{uuid.uuid4().hex}{safe_ext}"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_path}"

    try:
        data = image.read()
        req = urllib.request.Request(
            upload_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {service_role_key}",
                "apikey": service_role_key,
                "Content-Type": image.content_type or "application/octet-stream",
                "x-upsert": "true",
            },
        )
        urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError:
        request.session["flash_message"] = "Upload failed. Please try again."
        request.session["flash_message_type"] = "error"
        return redirect("staff_profile")
    except urllib.error.URLError:
        request.session["flash_message"] = "Network error during upload."
        request.session["flash_message_type"] = "error"
        return redirect("staff_profile")

    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_path}"

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    model.objects.filter(id=account_id).update(profile_path=public_url)

    request.session["flash_message"] = "Profile photo updated."
    request.session["flash_message_type"] = "success"
    return redirect("staff_profile")


@never_cache
def remove_staff_profile_image(request):
    if request.method != "POST":
        return redirect("staff_profile")

    account_id = request.session.get("account_id")
    account_type = request.session.get("account_type")
    if not account_id or account_type not in {"coordinator", "instructor"}:
        request.session["flash_message"] = "Please log in to continue."
        request.session["flash_message_type"] = "error"
        return redirect("front_page")

    supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
    service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    bucket = (os.getenv("SUPABASE_BUCKET") or "OJTSystemProfile").strip()

    model = PracticumCoordinator if account_type == "coordinator" else PracticumInstructor
    account = model.objects.filter(id=account_id).first()
    if not account:
        request.session["flash_message"] = "Account not found."
        request.session["flash_message_type"] = "error"
        return redirect("staff_profile")

    profile_url = (account.profile_path or "").strip()
    object_path = ""
    if supabase_url and bucket and profile_url.startswith(f"{supabase_url}/storage/v1/object/public/{bucket}/"):
        object_path = profile_url.split(f"/{bucket}/", 1)[-1]

    if object_path and service_role_key:
        delete_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_path}"
        try:
            req = urllib.request.Request(
                delete_url,
                method="DELETE",
                headers={
                    "Authorization": f"Bearer {service_role_key}",
                    "apikey": service_role_key,
                },
            )
            urllib.request.urlopen(req, timeout=20)
        except (urllib.error.HTTPError, urllib.error.URLError):
            # Even if delete fails, proceed to clear DB path
            pass

    model.objects.filter(id=account_id).update(profile_path=None)
    request.session["flash_message"] = "Profile photo removed."
    request.session["flash_message_type"] = "success"
    return redirect("staff_profile")


def logout_user(request):
    request.session.pop("account_id", None)
    request.session.pop("account_type", None)
    request.session["flash_message"] = "You have been logged out."
    request.session["flash_message_type"] = "success"
    return redirect("front_page")
