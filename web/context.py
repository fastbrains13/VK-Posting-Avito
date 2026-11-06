"""Общие данные для шаблонов."""

from __future__ import annotations

from core.models import VKAccount, VKCommunity


def active_community(request):
    """Добавить в контекст активное сообщество и аккаунт, если они есть."""
    if not request.user.is_authenticated:
        return {}
    community = VKCommunity.objects.filter(is_active=True).select_related("account").first()
    return {
        "active_community": community,
        "vk_account": community.account if community else VKAccount.objects.first(),
    }
