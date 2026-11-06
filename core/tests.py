from unittest.mock import patch

from django.test import TestCase

from .crypto import decrypt_token, encrypt_token


class TokenCipherTests(TestCase):
    def test_roundtrip(self):
        raw = "vk1.a.test-token-123"
        encrypted = encrypt_token(raw)
        self.assertNotEqual(encrypted, raw)
        self.assertEqual(decrypt_token(encrypted), raw)

    def test_empty(self):
        self.assertEqual(encrypt_token(""), "")
        self.assertEqual(decrypt_token(""), "")


class CommunityModelTests(TestCase):
    def test_community_token_is_encrypted(self):
        from .models import VKAccount, VKCommunity

        account = VKAccount.objects.create(token_encrypted=encrypt_token("token"))
        community = VKCommunity.objects.create(account=account, group_id=1, name="Тест")
        community.set_community_token("community-secret")
        community.save()
        self.assertTrue(community.has_community_token)
        self.assertEqual(community.community_token, "community-secret")
        self.assertEqual(community.community_token_mask, "…cret")
        self.assertNotEqual(community.community_token_encrypted, "community-secret")

    def test_long_avatar_url_is_saved(self):
        from .models import VKAccount, VKCommunity

        account = VKAccount.objects.create(token_encrypted=encrypt_token("token"))
        url = "https://sun9-1.userapi.com/" + "a" * 500 + "/photo.jpg"
        community = VKCommunity.objects.create(
            account=account, group_id=1, name="Тест", photo_url=url, is_active=True,
        )
        self.assertEqual(community.photo_url, url)


class ProxyTests(TestCase):
    def test_parse_formats(self):
        from core.proxies import parse_proxy_line

        item = parse_proxy_line("socks5://user:p%40ss@1.2.3.4:1080")
        self.assertEqual((item.scheme, item.host, item.port, item.username, item.password),
                         ("socks5", "1.2.3.4", 1080, "user", "p@ss"))
        item = parse_proxy_line("socks4://1.2.3.4:4145")
        self.assertEqual(item.scheme, "socks4")
        item = parse_proxy_line("5.6.7.8:3128")
        self.assertEqual((item.scheme, item.host, item.port), ("http", "5.6.7.8", 3128))
        item = parse_proxy_line("user:pass@9.9.9.9:8080")
        self.assertEqual((item.username, item.password), ("user", "pass"))
        from core.proxies import ProxyParseError

        with self.assertRaises(ProxyParseError):
            parse_proxy_line("http://1.2.3.4")
        with self.assertRaises(ProxyParseError):
            parse_proxy_line("ftp://1.2.3.4:21")

    @patch("core.proxies.check_proxy", return_value=(True, ""))
    def test_add_and_rotation(self, _check):
        from core.models import ProxyEndpoint
        from core.proxies import add_proxy_lines, pick_proxy

        result = add_proxy_lines("1.1.1.1:8080\n2.2.2.2:8080")
        self.assertEqual(result["ok"], 2)
        self.assertEqual(ProxyEndpoint.objects.count(), 2)
        first = pick_proxy(require_browser=True)
        second = pick_proxy(require_browser=True)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.pk, second.pk)

    @patch("core.proxies.check_proxy")
    def test_auto_detects_socks5(self, check):
        from core.models import ProxyEndpoint
        from core.proxies import add_proxy_lines

        def fake(parsed):
            return (parsed.scheme == "socks5", "http not available")

        check.side_effect = fake
        result = add_proxy_lines("1.2.3.4:1080")
        self.assertEqual(result["ok"], 1)
        self.assertEqual(ProxyEndpoint.objects.get().scheme, "socks5")

    @patch("core.proxies.check_proxy", return_value=(False, "timeout"))
    def test_bad_new_proxy_is_not_saved(self, _check):
        from core.models import ProxyEndpoint
        from core.proxies import add_proxy_lines

        result = add_proxy_lines("1.2.3.4:1080")
        self.assertEqual(result["bad"], 1)
        self.assertEqual(ProxyEndpoint.objects.count(), 0)

    @patch("core.proxies.check_proxy", return_value=(True, ""))
    def test_recheck_all(self, _check):
        from core.proxies import add_proxy_lines, recheck_all

        add_proxy_lines("1.2.3.4:1080")
        result = recheck_all()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["ok"], 1)

    def test_password_is_encrypted(self):
        from core.models import ProxyEndpoint

        proxy = ProxyEndpoint(scope=ProxyEndpoint.SCOPE_VK, scheme="http", host="1.2.3.4", port=8080)
        proxy.set_password("secret")
        proxy.save()
        self.assertNotEqual(proxy.password_encrypted, "secret")
        self.assertEqual(proxy.password, "secret")
        self.assertIn("1.2.3.4:8080", proxy.requests_url)
