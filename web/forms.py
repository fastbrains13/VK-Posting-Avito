"""Формы MVP."""

from __future__ import annotations

from urllib.parse import urlparse

from django import forms

from avito.models import AvitoSource


class VKTokenForm(forms.Form):
    token = forms.CharField(
        label="Пользовательский токен VK",
        widget=forms.PasswordInput(attrs={"autocomplete": "off", "placeholder": "vk1.a.…"}),
        help_text="Токен standalone-приложения с правами groups, wall, photos, offline. "
                  "Он хранится в зашифрованном виде.",
    )


class SourceForm(forms.ModelForm):
    class Meta:
        model = AvitoSource
        fields = ["url", "city", "title"]
        widgets = {
            "url": forms.URLInput(attrs={
                "placeholder": "https://www.avito.ru/moskva/avtomobili",
                "autocomplete": "off",
            }),
            "city": forms.TextInput(attrs={"placeholder": "Москва"}),
            "title": forms.TextInput(attrs={"placeholder": "Автомобили, Москва"}),
        }
        labels = {
            "url": "Ссылка на страницу выдачи",
            "city": "Город",
            "title": "Название источника",
        }

    def clean_url(self) -> str:
        url = (self.cleaned_data.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise forms.ValidationError("Ссылка должна начинаться с http:// или https://")
        if "avito.ru" not in parsed.netloc.lower():
            raise forms.ValidationError("Ссылка должна вести на avito.ru")
        return url
