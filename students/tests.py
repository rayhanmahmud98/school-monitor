from django.db.models import ProtectedError
from django.test import TestCase

from .models import Class, Enrollment, Student


def _class(name="Class 5", section="A", year="2026-2027"):
    return Class.objects.create(name=name, section=section, academic_year=year)


def _student(cls, roll, first="Test", last="Student", **extra):
    return Student.objects.create(first_name=first, last_name=last, roll_no=roll, class_ref=cls, **extra)


class StudentIdTests(TestCase):
    def test_ids_are_unique_and_sequential(self):
        cls = _class()
        ids = [_student(cls, n).student_id for n in range(1, 4)]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(all(i.startswith("STU-") for i in ids))


class EnrollmentSyncTests(TestCase):
    def test_new_student_gets_current_enrollment(self):
        cls = _class()
        s = _student(cls, 1)
        e = Enrollment.objects.get(student=s)
        self.assertTrue(e.is_current)
        self.assertEqual(e.class_ref, cls)

    def test_class_change_closes_old_and_opens_new(self):
        a, b = _class(section="A"), _class(section="B")
        s = _student(a, 1)
        s.class_ref = b
        s.save()
        old = Enrollment.objects.get(student=s, class_ref=a)
        new = Enrollment.objects.get(student=s, class_ref=b)
        self.assertFalse(old.is_current)
        self.assertIsNotNone(old.left_on)
        self.assertTrue(new.is_current)
        self.assertEqual(Enrollment.objects.filter(student=s, is_current=True).count(), 1)

    def test_deactivation_closes_enrollment(self):
        s = _student(_class(), 1)
        s.is_active = False
        s.save()
        self.assertFalse(Enrollment.objects.get(student=s).is_current)

    def test_reactivation_opens_new_enrollment(self):
        s = _student(_class(), 1)
        s.is_active = False
        s.save()
        s.is_active = True
        s.save()
        self.assertEqual(Enrollment.objects.filter(student=s, is_current=True).count(), 1)

    def test_resave_without_change_creates_nothing(self):
        s = _student(_class(), 1)
        s.save()
        s.save()
        self.assertEqual(Enrollment.objects.filter(student=s).count(), 1)


class ClassProtectionTests(TestCase):
    def test_class_with_students_cannot_be_deleted(self):
        cls = _class()
        _student(cls, 1)
        with self.assertRaises(ProtectedError):
            cls.delete()

    def test_empty_class_can_be_deleted(self):
        _class().delete()
        self.assertEqual(Class.objects.count(), 0)
