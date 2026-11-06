from django.contrib import admin

from .models import JobRun, ProxyEndpoint, VKAccount, VKCommunity


@admin.register(VKAccount)
class VKAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "display_name", "vk_user_id", "status", "token_mask", "last_checked_at")
    readonly_fields = ("token_encrypted", "token_mask", "token_last4", "created_at", "updated_at")


@admin.register(VKCommunity)
class VKCommunityAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "group_id", "account", "is_active", "can_post",
                    "can_upload_photos", "last_post_at")
    list_filter = ("is_active", "is_admin", "can_upload_photos")


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "progress", "created_at", "started_at", "finished_at")
    list_filter = ("kind", "status")
    readonly_fields = ("log", "result", "created_at", "started_at", "finished_at")


@admin.register(ProxyEndpoint)
class ProxyEndpointAdmin(admin.ModelAdmin):
    list_display = ("id", "scope", "scheme", "host", "port", "username", "status",
                    "is_active", "last_checked_at", "success_count", "fail_count")
    list_filter = ("scope", "scheme", "status", "is_active")
    readonly_fields = ("password_encrypted", "password_mask", "created_at", "updated_at")
