from django import forms

from .models import Class, Student, StudentDocument, Subject, TransferCertificate


class TailwindFormMixin:
    """Applies consistent Tailwind classes to every widget in a form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            base = (
                "w-full rounded-md border border-slate-300 px-3 py-2 text-sm "
                "shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
            )
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300")
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault(
                    "class",
                    "block w-full text-sm text-slate-600 file:mr-4 file:rounded-md "
                    "file:border-0 file:bg-indigo-50 file:px-4 file:py-2 "
                    "file:text-sm file:font-medium file:text-indigo-700 hover:file:bg-indigo-100",
                )
            else:
                widget.attrs.setdefault("class", base)


class ClassForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Class
        fields = ("name", "section", "academic_year", "max_students")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["max_students"].help_text = (
            "Maximum number of active students allowed in this class."
        )


class SubjectForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Subject
        fields = ("name", "code", "class_ref", "teacher")


class StudentForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = (
            # Identification
            "student_id", "first_name", "middle_name", "last_name", "preferred_name",
            "photo", "blood_group",
            # Demographics
            "date_of_birth", "gender", "nationality", "ethnicity", "religion",
            # Academic placement
            "class_ref", "roll_no", "admission_date", "is_active",
            # Contact
            "address_line1", "address_line2", "city", "postal_code",
            "mailing_address", "phone", "email",
            # Guardian quick reference
            "guardian_name", "contact", "user_link",
        )
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "admission_date": forms.DateInput(attrs={"type": "date"}),
            "mailing_address": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student_id"].required = False
        self.fields["student_id"].help_text = "Leave blank to auto-generate (STU-YYYY-NNNN)."
        for optional in (
            "middle_name", "preferred_name", "photo", "blood_group",
            "date_of_birth", "gender", "nationality", "ethnicity", "religion",
            "admission_date", "address_line1", "address_line2", "city",
            "postal_code", "mailing_address", "phone", "email",
        ):
            if optional in self.fields:
                self.fields[optional].required = False

    def clean(self):
        """Refuse to add or move an active student into a full class."""
        cleaned = super().clean()
        target_class = cleaned.get("class_ref")
        is_active = cleaned.get("is_active", True)

        if not target_class or not is_active:
            return cleaned

        # Count active students currently in the target class.
        existing = target_class.students.filter(is_active=True)
        # If editing, exclude this row so we don't count it against itself.
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)

        if existing.count() >= target_class.max_students:
            raise forms.ValidationError(
                f"{target_class} is full "
                f"({target_class.max_students} / {target_class.max_students} seats taken). "
                "Move a student out or raise the class capacity first."
            )
        return cleaned


class StudentDocumentForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = StudentDocument
        fields = ("kind", "title", "file", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False
        self.fields["notes"].required = False

class TransferCertificateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = TransferCertificate
        fields = (
            "tc_number", "reason", "reason_note", "conduct",
            "dues_cleared", "date_of_leaving", "remarks",
        )
        widgets = {
            "date_of_leaving": forms.DateInput(attrs={"type": "date"}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
            "reason_note": forms.TextInput(attrs={"placeholder": "Optional detail"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tc_number"].required = False
        self.fields["tc_number"].help_text = "Leave blank to auto-generate (TC-YYYY-NNNN)."
        self.fields["conduct"].required = False
        self.fields["reason_note"].required = False
        self.fields["remarks"].required = False
