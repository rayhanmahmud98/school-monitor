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
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300")
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

    def save(self, commit=True):
        user = super().save(commit=False)
        raw = self.cleaned_data.get("password")
        if raw:
            user.set_password(raw)
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
        fields = ("user", "subject_specialization", "phone")


class ParentStudentLinkForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ParentStudentLink
        fields = ("parent", "student", "relationship")