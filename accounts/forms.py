from django import forms
from django.contrib.auth.forms import AuthenticationForm

from students.models import ParentStudentLink

from .models import ParentProfile, TeacherProfile, User


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


class LoginForm(TailwindFormMixin, AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput)


class UserAdminForm(TailwindFormMixin, forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput, required=False,
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "role", "is_active")

    def clean(self):
        cleaned = super().clean()
        # Lock down the primary admin: nobody can change its username, role, or active status.
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
        # Belt and suspenders: never deactivate the primary admin
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
        fields = ("user", "subject_specialization", "designation", "phone")


class ParentStudentLinkForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ParentStudentLink
        fields = ("parent", "student", "relationship")


class TeacherForm(TailwindFormMixin, forms.ModelForm):
    """Creates or edits a teacher (User + TeacherProfile in one step)."""

    password = forms.CharField(
        widget=forms.PasswordInput, required=False,
        help_text="Leave blank to keep the current password.",
    )
    designation = forms.ChoiceField(
        choices=TeacherProfile.Designation.choices,
        required=True,
    )
    subject_specialization = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(max_length=30, required=False)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            profile = getattr(self.instance, "teacher_profile", None)
            if profile:
                self.fields["designation"].initial = profile.designation
                self.fields["subject_specialization"].initial = profile.subject_specialization
                self.fields["phone"].initial = profile.phone

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
            profile.subject_specialization = self.cleaned_data.get("subject_specialization", "")
            profile.phone = self.cleaned_data.get("phone", "")
            profile.save()
        return user