import io
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.sunat_api import SunatGreConnectionView
from core.sunat_gre import GreConnectionError, gre_configuration, verify_gre_oauth


class GreConnectionTests(SimpleTestCase):
    url = "/api/admin/erp/sunat/gre/conexion/"

    def admin_request(self, method="get", data=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)(self.url, data=data or {}, format="json")
        force_authenticate(request, user=SimpleNamespace(
            is_authenticated=True, is_superuser=True,
        ))
        return SunatGreConnectionView.as_view()(request)

    def test_unconfigured_get_returns_metadata_without_secret(self):
        with patch.dict(os.environ, {
            "SUNAT_GRE_CLIENT_ID": "",
            "SUNAT_GRE_CLIENT_SECRET": "",
            "SUNAT_GRE_SOL_PASSWORD": "",
            "SUNAT_GRE_CONNECTIVITY_ENABLED": "false",
        }):
            response = self.admin_request()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["configured"])
        self.assertFalse(response.data["gre_emission_enabled"])
        self.assertNotIn("client_secret", response.data)
        self.assertNotIn("access_token", response.data)

    def test_anonymous_is_denied_and_payload_is_rejected(self):
        response = SunatGreConnectionView.as_view()(APIRequestFactory().get(self.url))
        self.assertIn(response.status_code, (401, 403))
        response = self.admin_request("post", {"password": "inseguro"})
        self.assertEqual(response.status_code, 400)

    def test_disabled_connection_never_contacts_external_service(self):
        with patch.dict(os.environ, {"SUNAT_GRE_CONNECTIVITY_ENABLED": "false"}):
            with patch("core.sunat_gre.urlopen") as opener:
                with self.assertRaises(GreConnectionError):
                    verify_gre_oauth()
                opener.assert_not_called()

    def test_enabled_oauth_uses_only_backend_and_hides_access_token(self):
        secret = "CLAVE_SUPER_SECRETA"
        env = {
            "SUNAT_GRE_CONNECTIVITY_ENABLED": "true",
            "SUNAT_GRE_RUC": "20601658811",
            "SUNAT_GRE_CLIENT_ID": "c4c76f42-0123-4567-89ab-123456789abc",
            "SUNAT_GRE_CLIENT_SECRET": "CLIENTE_SECRETO",
            "SUNAT_GRE_SOL_USER": "USUARIOSEC",
            "SUNAT_GRE_SOL_PASSWORD": secret,
        }
        def fake_open(request, timeout):
            self.assertEqual(timeout, 8)
            self.assertTrue(request.full_url.startswith(
                "https://api-seguridad.sunat.gob.pe/v1/clientessol/"
            ))
            form = parse_qs(request.data.decode())
            self.assertEqual(form["scope"], ["https://api-cpe.sunat.gob.pe"])
            self.assertEqual(form["grant_type"], ["password"])
            self.assertEqual(form["username"], ["20601658811USUARIOSEC"])
            self.assertEqual(form["password"], [secret])
            return io.BytesIO(json.dumps({"access_token": "NO-MOSTRAR"}).encode())

        with patch.dict(os.environ, env):
            with patch("core.sunat_gre.urlopen", side_effect=fake_open) as mock_open:
                response = self.admin_request("post")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["authenticated"])
        self.assertFalse(response.data["gre_emission_enabled"])
        self.assertNotIn("access_token", response.data)
        self.assertNotIn(secret, str(response.data))
        mock_open.assert_called_once()
