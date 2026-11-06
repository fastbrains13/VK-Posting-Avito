from django.contrib import admin

from .models import Publication


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ("id", "ad", "community", "status", "attempts", "vk_post_id", "created_at")
    list_filter = ("status", "community")
    search_fields = ("ad__avito_id", "ad__title", "vk_post_id")
    readonly_fields = ("message", "attachments", "guid", "created_at", "updated_at", "posted_at")
