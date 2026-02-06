from django.db import models
import uuid


class Student(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    student_no = models.TextField(unique=True)
    cca_email = models.EmailField(unique=True)
    last_name = models.TextField()
    first_name = models.TextField()
    second_name = models.TextField(blank=True, null=True)
    middle_initial = models.TextField(blank=True, null=True)
    school_year = models.TextField(blank=True, null=True)
    program = models.TextField()
    section = models.TextField()
    password = models.TextField()
    activation_code = models.TextField()
    recovery_code = models.TextField(blank=True, null=True)
    active_status = models.BooleanField(default=False)
    is_password_temp = models.BooleanField(default=True)
    profile_path = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "students"
        managed = False


class PracticumCoordinator(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cca_email = models.EmailField(unique=True)
    last_name = models.TextField()
    first_name = models.TextField()
    second_name = models.TextField(blank=True, null=True)
    middle_initial = models.TextField(blank=True, null=True)
    password = models.TextField()
    activation_code = models.TextField(blank=True, null=True)
    recovery_code = models.TextField(blank=True, null=True)
    active_status = models.BooleanField(default=False)
    is_password_temp = models.BooleanField(default=True)
    profile_path = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "practicum_coordinators"
        managed = False


class PracticumInstructor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cca_email = models.EmailField(unique=True)
    last_name = models.TextField()
    first_name = models.TextField()
    second_name = models.TextField(blank=True, null=True)
    middle_initial = models.TextField(blank=True, null=True)
    password = models.TextField()
    activation_code = models.TextField(blank=True, null=True)
    recovery_code = models.TextField(blank=True, null=True)
    active_status = models.BooleanField(default=False)
    is_password_temp = models.BooleanField(default=True)
    profile_path = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "practicum_instructors"
        managed = False
