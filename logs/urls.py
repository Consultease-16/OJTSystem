from django.urls import path

from . import views

urlpatterns = [
    path('', views.front_page, name='front_page'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('activate/', views.activate_account, name='activate_account'),
    path('change-password/', views.change_temp_password, name='change_temp_password'),
    path('student/', views.student_home, name='student_home'),
    path('staff/', views.staff_home, name='staff_home'),
    path('staff/manage-records/', views.manage_records, name='manage_records'),
    path('staff/company-checklist/', views.company_checklist, name='company_checklist'),
    path('staff/company-checklist/data/', views.company_checklist_data, name='company_checklist_data'),
    path('staff/manage-records/sync/', views.sync_student_requirements_view, name='sync_student_requirements'),
    path('staff/manage-records/update/', views.update_student_requirement, name='update_student_requirement'),
    path('staff/section-instructors/', views.section_instructors_view, name='section_instructors'),
    path('staff/schedules/', views.schedules_view, name='schedules'),
    path('staff/weekly-journal/weeks/', views.weekly_journal_weeks, name='weekly_journal_weeks'),
    path('staff/weekly-journal/check/', views.update_weekly_journal_check, name='weekly_journal_check'),
    path('staff/manage-accounts/', views.manage_accounts, name='manage_accounts'),
    path('staff/handled-sections/', views.instructor_sections, name='instructor_sections'),
    path(
        'staff/handled-sections/<uuid:section_id>/details/',
        views.instructor_section_details,
        name='instructor_section_details',
    ),
    path('staff/profile/', views.staff_profile, name='staff_profile'),
    path('staff/profile/upload/', views.upload_staff_profile_image, name='upload_staff_profile_image'),
    path('staff/profile/remove/', views.remove_staff_profile_image, name='remove_staff_profile_image'),
    path('logout/', views.logout_user, name='logout'),
]
