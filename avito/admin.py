from django.contrib import admin

from .models import Ad, AdPhoto, AvitoSource


class AdPhotoInline(admin.TabularInline):
    model = AdPhoto
    extra = 0
    readonly_fields = ("image_url", "file", "status", "error", "sha256")


@admin.register(AvitoSource)
class AvitoSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "url", "city", "last_parsed_at", "last_status")


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ("avito_id", "title", "price_text", "location", "detail_status", "source")
    list_filter = ("detail_status",)
    search_fields = ("avito_id", "title", "url")
    inlines = [AdPhotoInline]
