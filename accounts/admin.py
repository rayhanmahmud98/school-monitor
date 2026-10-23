from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LoginHistory, ParentProfile, TeacherProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "get_full_name", "email", "role", "is_active")
    list_filter = ("role", "is_active")


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone")
    search_fields = ("user__username", "phone")


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "employee_id", "subject_specialization", "phone")
    search_fields = ("user__username", "employee_id", "subject_specialization")


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "timestamp", "ip_address", "user_agent_short")
    list_filter = ("timestamp",)
    search_fields = ("user__username", "ip_address", "user_agent")
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)
    readonly_fields = ("user", "timestamp", "ip_address", "user_agent", "session_key")

    @admin.display(description="User agent")
    def user_agent_short(self, obj):
        return (obj.user_agent[:60] + "…") if len(obj.user_agent) > 60 else obj.user_agent