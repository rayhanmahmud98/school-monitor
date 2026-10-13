"""
Populate the database with demo data spanning the last 3 academic years:

    python manage.py seed_data            # add / update demo data (safe to re-run)
    python manage.py seed_data --reset    # wipe school data + demo users first
    python manage.py seed_data --no-pdfs  # skip report card PDF generation (faster)

Generates:
  * 3 academic years:  <current-2>-<current-1>, <current-1>-<current>, <current>-<current+1>
  * 6 teachers, ~20 parents, 50 students, 6 classes per year (sections A & B)
  * Attendance for every weekday across all 3 years
  * 3 exams per year (First Term, Midterm, Final) with marksheets
  * Report cards for past years (published) and current year (unpublished)
"""
import random
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import ParentProfile, TeacherProfile, User
from academics.models import (AcademicYear, Attendance, AuditLog, Exam, GradeScale, Marksheet,
                              ReportCard)
from academics.services import DEFAULT_SCALE
from academics.views import _generate_report_card
from students.models import Class, ParentStudentLink, Student, Subject

TEACHERS = [
    ("teacher1", "Ayesha", "Karim", "Mathematics"),
    ("teacher2", "Imran", "Hossain", "English"),
    ("teacher3", "Nadia", "Rahman", "Science"),
    ("teacher4", "Farhan", "Ali", "Mathematics"),
    ("teacher5", "Rukhsana", "Begum", "English"),
    ("teacher6", "Sabbir", "Chowdhury", "Science"),
]

PARENTS = [
    ("parent1", "Rahim", "Uddin"),
    ("parent2", "Sultana", "Chowdhury"),
    ("parent3", "Karim", "Siddique"),
    ("parent4", "Farhana", "Ahmed"),
    ("parent5", "Jamal", "Khan"),
    ("parent6", "Nasrin", "Akter"),
    ("parent7", "Mahmud", "Hasan"),
    ("parent8", "Shirin", "Sultana"),
    ("parent9", "Anwar", "Hossain"),
    ("parent10", "Rokeya", "Islam"),
    ("parent11", "Tariq", "Rahman"),
    ("parent12", "Salma", "Khatun"),
    ("parent13", "Noman", "Chowdhury"),
    ("parent14", "Rashida", "Begum"),
    ("parent15", "Iqbal", "Hossain"),
    ("parent16", "Nargis", "Akter"),
    ("parent17", "Kamal", "Uddin"),
    ("parent18", "Rehana", "Parvin"),
    ("parent19", "Sohel", "Rana"),
    ("parent20", "Moushumi", "Das"),
]

# class name -> [(subject, code, teacher_index)]
PLAN = {
    "Class 8": [("Mathematics", "MATH", 0), ("English", "ENG", 1), ("Science", "SCI", 2)],
    "Class 9": [("Mathematics", "MATH", 3), ("English", "ENG", 4), ("Science", "SCI", 5)],
    "Class 10": [("Mathematics", "MATH", 0), ("English", "ENG", 1), ("Science", "SCI", 2)],
}

FIRST_NAMES = [
    "Aarav", "Maya", "Tanvir", "Nusrat", "Sami", "Zara", "Rafi", "Lamia", "Arif", "Tasnim",
    "Omar", "Priya", "Fahim", "Anika", "Shafin", "Nabila", "Ruhan", "Ishrat", "Sadman", "Mim",
    "Ridoy", "Sumaiya", "Tahmid", "Jannat", "Nafis", "Mehjabin", "Shakib", "Prova", "Adnan",
    "Farhana", "Rasel", "Tania", "Imran", "Sanjida", "Rony", "Sharmin", "Naim", "Lubna",
    "Foysal", "Rubaiya", "Tanim", "Afsana", "Sohan", "Maliha", "Rakib", "Nusrat", "Hasib",
    "Tasfia", "Zubair", "Anjuman",
]

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
RELIGIONS = ["Islam", "Hinduism", "Christianity", "Buddhism"]
CITIES = ["Dhaka", "Chattogram", "Khulna", "Rajshahi", "Sylhet"]
RELATIONSHIPS = ["Father", "Mother", "Guardian"]


class Command(BaseCommand):
    help = "Seed demo data covering the last 3 academic years."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing school data first.")
        parser.add_argument("--no-pdfs", action="store_true", help="Skip report card PDF generation.")

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(42)
        today = timezone.localdate()

        # ---------- reset ------------------------------------------------
        if opts["reset"]:
            for model in (Marksheet, Attendance, ReportCard, ParentStudentLink, Student,
                          Subject, Class, Exam):
                model.objects.all().delete()
            names = ["admin"] + [t[0] for t in TEACHERS] + [p[0] for p in PARENTS]
            User.objects.filter(username__in=names).delete()
            self.stdout.write("Existing demo data removed.")

        # ---------- academic years --------------------------------------
        # Compute school years. A school year labelled YYYY-YYYY+1 begins in April.
        base_start = today.year if today.month >= 4 else today.year - 1
        year_names = [f"{base_start + i}-{base_start + i + 1}" for i in (-2, -1, 0)]
        current_year = year_names[-1]
        for i, name in enumerate(year_names):
            AcademicYear.objects.update_or_create(
                name=name, defaults={"is_current": (name == current_year)})

        for minimum, grade, points in DEFAULT_SCALE:
            GradeScale.objects.update_or_create(
                min_percent=minimum, defaults={"grade": grade, "gpa_points": points})

        # ---------- exam types ------------------------------------------
        from academics.models import ExamType
        for tname, weight in [("Unit Test", 30), ("Midterm", 50), ("Final", 100)]:
            ExamType.objects.update_or_create(
                name=tname, defaults={"weight": weight, "is_active": True})

        # ---------- users -----------------------------------------------
        def make_user(username, password, role, first, last, **extra):
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last,
                          "email": f"{username}@example.com", "role": role, **extra})
            user.set_password(password)
            user.save()
            return user

        admin = make_user("admin", "admin123", "ADMIN", "System", "Admin", is_superuser=True)

        teachers = []
        for i, (u, first, last, spec) in enumerate(TEACHERS, start=1):
            t = make_user(u, "teacher123", "TEACHER", first, last)
            TeacherProfile.objects.update_or_create(
                user=t, defaults={"subject_specialization": spec, "phone": f"01800-000{i:03d}"})
            teachers.append(t)

        parents = []
        for i, (u, first, last) in enumerate(PARENTS, start=1):
            p = make_user(u, "parent123", "PARENT", first, last)
            ParentProfile.objects.update_or_create(
                user=p, defaults={"phone": f"01900-000{i:03d}", "address": f"{i} Lake Road"})
            parents.append(p)

        # ---------- classes + subjects per year -------------------------
        # Build a Class row for each (year, name, section).
        section_names = ["A", "B"]
        class_by_year = {y: [] for y in year_names}
        subject_by_class = {}
        for y in year_names:
            for name in ("Class 8", "Class 9", "Class 10"):
                for section in section_names:
                    cls, _ = Class.objects.get_or_create(
                        name=name, section=section, academic_year=y)
                    class_by_year[y].append(cls)
                    for subj_name, code, t_idx in PLAN[name]:
                        s, _ = Subject.objects.update_or_create(
                            code=code, class_ref=cls,
                            defaults={"name": subj_name, "teacher": teachers[t_idx]})
                        subject_by_class.setdefault(cls.pk, []).append(s)

        # ---------- students --------------------------------------------
        # 50 students, one per name slot, distributed across current-year classes.
        # Each student also gets Enrollment rows for every year they were enrolled.
        current_classes = class_by_year[current_year]
        # filter out teachers index; we just need a class per student
        total_students = 50
        students = []
        name_pool = FIRST_NAMES * 2  # duplicate to reach 50 unique-ish names
        for k in range(total_students):
            first = name_pool[k]
            last = parents[k % len(parents)].last_name
            gender = rng.choice(["M", "F"])
            age = 13 + (k % 3)
            dob = date(today.year - age, rng.randint(1, 12), rng.randint(1, 28))
            cls = current_classes[k % len(current_classes)]
            student, _ = Student.objects.update_or_create(
                class_ref=cls, roll_no=(k % 25) + 1,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "full_name": f"{first} {last}",
                    "date_of_birth": dob,
                    "gender": gender,
                    "blood_group": rng.choice(BLOOD_GROUPS),
                    "nationality": "Bangladeshi",
                    "religion": rng.choice(RELIGIONS),
                    "address_line1": f"House {rng.randint(1, 200)}",
                    "address_line2": f"Road {rng.randint(1, 30)}",
                    "city": rng.choice(CITIES),
                    "postal_code": f"{rng.randint(1000, 9999)}",
                    "phone": f"01700-{k:05d}",
                    "email": f"student{k+1:03d}@example.com",
                    "guardian_name": parents[k % len(parents)].display_name,
                    "contact": f"01700-{k:05d}",
                    "admission_date": date(today.year - 3, 1, 10),
                    "is_active": True,
                })
            students.append(student)

            # Parent link (rotate through the parent pool)
            parent = parents[k % len(parents)]
            ParentStudentLink.objects.get_or_create(
                parent=parent, student=student,
                defaults={
                    "relationship": rng.choice(RELATIONSHIPS),
                    "is_primary": True,
                })

        # ---------- exams, marks, attendance, report cards per year -----
        today_dt = timezone.now()
        now = today_dt
        published_cards = 0
        for year_idx, year_name in enumerate(year_names):
            is_current = (year_name == current_year)
            year_start = date(base_start + year_idx - 2 + 2, 4, 1)  # April 1 of year YYYY
            # The line above is intentionally simple: each school year starts April 1.
            # year_idx = 0 -> two years ago; year_idx = 2 -> this year.
            y = base_start + (year_idx - 2)
            year_start = date(y, 4, 1)
            year_end = date(y + 1, 3, 31)

            # --- exams for this year -----------------------------------
            term_dates = {
                "First Term": (year_start + timedelta(days=60),  year_start + timedelta(days=70)),
                "Midterm":    (year_start + timedelta(days=150), year_start + timedelta(days=160)),
                "Final":      (year_start + timedelta(days=300), year_start + timedelta(days=310)),
            }
            year_exams = {}
            for term, (s_date, e_date) in term_dates.items():
                # Skip exams that haven't started yet
                if s_date > today:
                    continue
                published = (term != "Final") or not is_current
                exam, _ = Exam.objects.update_or_create(
                    name=term, academic_year=year_name,
                    defaults={"start_date": s_date, "end_date": e_date,
                              "is_published": published})
                year_exams[term] = exam

            # --- attendance for the whole school year ----------------
            class_teacher = {}
            for cls in class_by_year[year_name]:
                subs = subject_by_class.get(cls.pk, [])
                if subs:
                    class_teacher[cls.pk] = subs[0].teacher
            day = year_start
            while day <= year_end and day <= today:
                if day.weekday() >= 5:  # skip weekends
                    day += timedelta(days=1)
                    continue
                for st in students:
                    # Only mark a student on days they were enrolled.
                    # Simple rule: student is enrolled from admission_date onward.
                    if st.admission_date and day < st.admission_date:
                        continue
                    status = rng.choices(
                        ["PRESENT", "ABSENT", "LATE", "EXCUSED"],
                        weights=[84, 8, 6, 2])[0]
                    Attendance.objects.update_or_create(
                        student=st, date=day,
                        defaults={
                            "status": status,
                            "marked_by": class_teacher.get(st.class_ref_id),
                            "marked_at": timezone.make_aware(
                                datetime.combine(day, time(9, 5))),
                            "remarks": "Doctor's note" if status == "EXCUSED" else "",
                        })
                day += timedelta(days=1)

            # --- marksheets for each exam of this year ----------------
            for term, exam in year_exams.items():
                for st in students:
                    subs = subject_by_class.get(st.class_ref_id, [])
                    for subj in subs:
                        # Past-year exams are APPROVED; current Midterm is SUBMITTED
                        if is_current and term == "Midterm":
                            status = "SUBMITTED"
                            submitted = now - timedelta(days=5)
                            approved_at = None
                            approved_by = None
                        elif is_current and term == "First Term":
                            status = "APPROVED"
                            submitted = now - timedelta(days=90)
                            approved_at = now - timedelta(days=88)
                            approved_by = admin
                        else:
                            status = "APPROVED"
                            submitted = now - timedelta(days=200)
                            approved_at = now - timedelta(days=198)
                            approved_by = admin

                        Marksheet.objects.update_or_create(
                            student=st, subject=subj, exam=exam,
                            defaults={
                                "marks_obtained": rng.randint(38, 98),
                                "max_marks": 100,
                                "entered_by": subj.teacher,
                                "status": status,
                                "submitted_at": submitted,
                                "approved_at": approved_at,
                                "approved_by": approved_by,
                            })

            # --- report cards for past years' Final exams -------------
            if not opts["no_pdfs"]:
                try:
                    final_exam = year_exams.get("Final")
                    if final_exam and not is_current:
                        for st in students:
                            card = _generate_report_card(st, final_exam)
                            if card:
                                card.published_at = today_dt
                                card.published_by = admin
                                card.save()
                                published_cards += 1
                except ImportError:
                    self.stdout.write(self.style.WARNING(
                        "reportlab not installed — skipped PDFs."))
                    opts["no_pdfs"] = True

        AuditLog.objects.create(user=admin, action="SEED_DATA",
                                details="Demo data spanning 3 academic years created")

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(year_names)} academic years, {total_students} students, "
            f"{len(teachers)} teachers, {len(parents)} parents, "
            f"{Attendance.objects.count()} attendance records, "
            f"{Marksheet.objects.count()} marksheets, "
            f"{published_cards} published report cards."))
        self.stdout.write(
            "\nLogins:\n"
            "  admin      / admin123\n"
            "  teacher1..6 / teacher123\n"
            "  parent1..20 / parent123"
        )