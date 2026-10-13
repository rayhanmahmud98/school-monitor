"""
Data-scoping helpers. Views must obtain students/classes/subjects ONLY through
these functions so a teacher or parent can never reach data outside their scope.
"""
from students.models import Class, Student, Subject

from .models import User


def teacher_subjects(user):
    return Subject.objects.filter(teacher=user).select_related("class_ref")


def teacher_classes(user):
    return Class.objects.filter(subjects__teacher=user).distinct()


def teacher_students(user):
    return Student.objects.filter(class_ref__subjects__teacher=user).distinct()


def parent_students(user):
    return Student.objects.filter(parent_links__parent=user).distinct()


def scoped_students(user):
    """Students the given user is allowed to see."""
    if user.role == User.Role.ADMIN:
        return Student.objects.all()
    if user.role == User.Role.TEACHER:
        return teacher_students(user)
    if user.role == User.Role.PARENT:
        return parent_students(user)
    return Student.objects.none()
