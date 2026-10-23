from django import forms
from django.contrib.auth.forms import AuthenticationForm
import datetime

from students.models import ParentStudentLink
from .models import ParentProfile, TeacherProfile, User


class TailwindFormMixin:
    """Applies consistent Tailwind classes to every widget in a form."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            base = ("w-full rounded-md border border-slate-300 px-3 py-2 text-sm "
                    "shadow-sm focus:border-indigo-500 focus:ring-indigo-500")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300")
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault("class", "block w-full text-sm text-slate-600 file:mr-4 file:rounded-md file:border-0 file:bg-indigo-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-indigo-700 hover:file:bg-indigo-100")
            else:
                widget.attrs.setdefault("class", base)


class LoginForm(TailwindFormMixin, AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput)


class UserAdminForm(TailwindFormMixin, forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False, help_text="Leave blank to keep the current password.")
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "role", "is_active")

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk and self.instance.is_primary_admin:
            cleaned["username"] = self.instance.username
            cleaned["role"] = self.instance.role
            cleaned["is_active"] = True
            if not self.instance.is_active:
                self.instance.is_active = True
                self.instance.save(update_fields=["is_active"])
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        raw = self.cleaned_data.get("password")
        if raw:
            user.set_password(raw)
        if user.pk and user.is_primary_admin:
            user.is_active = True
        if commit:
            user.save()
        return user


class ParentProfileForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ParentProfile
        fields = ("user", "phone", "address")


class TeacherProfileForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = TeacherProfile
        fields = ("user", "subject_specialization", "designation", "phone", "blood_group")


class ParentStudentLinkForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ParentStudentLink
        fields = ("parent", "student", "relationship")


class TeacherForm(TailwindFormMixin, forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False, help_text="Leave blank to keep the current password.")
    designation = forms.ChoiceField(choices=TeacherProfile.Designation.choices, required=True)
    blood_group = forms.ChoiceField(choices=TeacherProfile.BloodGroup.choices, required=False)
    subject_specialization = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(max_length=30, required=False)
    employee_id = forms.CharField(max_length=30, required=False, help_text="Leave blank to auto-generate (EMP-YYYY-NNNN).")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            profile = getattr(self.instance, "teacher_profile", None)
            if profile:
                self.fields["designation"].initial = profile.designation
                self.fields["blood_group"].initial = profile.blood_group
                self.fields["subject_specialization"].initial = profile.subject_specialization
                self.fields["phone"].initial = profile.phone
                self.fields["employee_id"].initial = profile.employee_id

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = "TEACHER"
        raw = self.cleaned_data.get("password")
        if raw:
            user.set_password(raw)
        elif not user.pk:
            user.set_unusable_password()

        if commit:
            user.save()
            profile, _ = TeacherProfile.objects.get_or_create(user=user)
            profile.designation = self.cleaned_data.get("designation", "")
            profile.blood_group = self.cleaned_data.get("blood_group", "")
            profile.subject_specialization = self.cleaned_data.get("subject_specialization", "")
            profile.phone = self.cleaned_data.get("phone", "")
            
            # Auto-generate employee_id if missing
            emp_id = self.cleaned_data.get("employee_id")
            if emp_id:
                profile.employee_id = emp_id
            elif not profile.employee_id:
                year = datetime.datetime.now().year
                prefix = f"EMP-{year}-"
                last = TeacherProfile.objects.filter(employee_id__startswith=prefix).order_by("-employee_id").first()
                if last and last.employee_id:
                    try:
                        num = int(last.employee_id.rsplit("-", 1)[1]) + 1
                    except (ValueError, IndexError):
                        num = 1
                else:
                    num = 1
                profile.employee_id = f"{prefix}{num:04d}"
                
            profile.save()
        return user