from django import forms

from accounts.forms import TailwindFormMixin

from .models import AcademicYear, Attendance, Exam, ExamType, GradeScale, LeaveApplication


class ExamTypeForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ExamType
        fields = ("name", "description", "weight", "is_active")


class ExamForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Exam
        fields = ["name", "exam_type", "academic_year", "start_date", "end_date", "is_published"]

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
        return cleaned


class AcademicYearForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "is_current"]


class GradeScaleForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = GradeScale
        fields = ["min_percent", "grade", "gpa_points"]


class AttendanceEditForm(TailwindFormMixin, forms.ModelForm):
    """Admin override of a single attendance entry."""

    class Meta:
        model = Attendance
        fields = ["status", "remarks"]

class LeaveApplicationForm(TailwindFormMixin, forms.ModelForm):
    """Form for filing a leave request.

    The `user` kwarg controls the choices:
      - Teacher: sees only themselves in the teacher picker; student picker hidden.
      - Parent:  sees only their own children in the student picker; teacher hidden.
      - Admin:   sees everyone (edge cases only).
    """

    class Meta:
        model = LeaveApplication
        fields = ("applicant_type", "student", "teacher",
                  "start_date", "end_date", "reason")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        from students.models import Student
        from accounts.scope import parent_students

        # Default querysets, then narrow by role
        student_qs = Student.objects.filter(is_active=True).order_by("class_ref", "roll_no")
        teacher_qs = self.fields["teacher"].queryset.order_by("first_name", "last_name")

        if self.user is not None:
            role = getattr(self.user, "role", None)

            if role == "TEACHER":
                # Teacher can only file for themselves
                self.fields["applicant_type"].initial = LeaveApplication.Applicant.TEACHER
                self.fields["applicant_type"].disabled = True
                teacher_qs = teacher_qs.filter(pk=self.user.pk)
                self.fields["teacher"].initial = self.user.pk
                self.fields["teacher"].disabled = True
                self.fields["student"].widget = forms.HiddenInput()
                self.fields["student"].required = False

            elif role == "PARENT":
                # Parent can only file for their own children
                self.fields["applicant_type"].initial = LeaveApplication.Applicant.STUDENT
                self.fields["applicant_type"].disabled = True
                student_qs = parent_students(self.user).filter(is_active=True).order_by("full_name")
                self.fields["teacher"].widget = forms.HiddenInput()
                self.fields["teacher"].required = False

        self.fields["student"].queryset = student_qs
        self.fields["teacher"].queryset = teacher_qs
        self.fields["student"].required = False
        self.fields["teacher"].required = False

    def clean(self):
        cleaned = super().clean()
        app_type = cleaned.get("applicant_type")
        student = cleaned.get("student")
        teacher = cleaned.get("teacher")
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")

        if app_type == LeaveApplication.Applicant.STUDENT and not student:
            self.add_error("student", "Pick a student for a student leave.")
        if app_type == LeaveApplication.Applicant.TEACHER and not teacher:
            self.add_error("teacher", "Pick a teacher for a teacher leave.")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before start date.")

        # Soft guardrails on dates
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        if start and start < today - timedelta(days=1):
            self.add_error("start_date", "Start date cannot be more than a day in the past.")
        if start and start > today + timedelta(days=365):
            self.add_error("start_date", "Start date is too far in the future.")

        return cleaned


class LeaveReviewForm(TailwindFormMixin, forms.Form):
    """Admin review form: approve or reject with a note."""

    action = forms.ChoiceField(choices=(("APPROVE", "Approve"), ("REJECT", "Reject")))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                           help_text="Required when rejecting.")

class LeaveReviewForm(TailwindFormMixin, forms.Form):
    """Admin review form: approve or reject with a note."""

    action = forms.ChoiceField(choices=(("APPROVE", "Approve"), ("REJECT", "Reject")))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                           help_text="Required when rejecting.")
