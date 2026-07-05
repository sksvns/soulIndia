from django.contrib import admin
from django.contrib.auth import get_user_model

User = get_user_model()


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("email", "full_name")
    filter_horizontal = ("groups", "user_permissions")
    exclude = ("password",)
