"""Conector GRE: SOLO verificación OAuth. No crea ni emite guías.

No registrar respuestas de SUNAT, token, usuario SOL ni contraseñas en logs.
La emisión requiere XML UBL firmado, envío, ticket y CDR aceptada.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

SUNAT_TOKEN_HOST = "https://api-seguridad.sunat.gob.pe"
GRE_SCOPE = "https://api-cpe.sunat.gob.pe"
REQUIRED = (
    "SUNAT_GRE_RUC", "SUNAT_GRE_CLIENT_ID", "SUNAT_GRE_CLIENT_SECRET",
    "SUNAT_GRE_SOL_USER", "SUNAT_GRE_SOL_PASSWORD",
)


def gre_configuration():
    missing = [key for key in REQUIRED if not os.getenv(key, "").strip()]
    enabled = os.getenv("SUNAT_GRE_CONNECTIVITY_ENABLED", "false").lower() == "true"
    return {
        "configured": not missing,
        "connectivity_enabled": enabled,
        "missing_fields": missing,
        "gre_emission_enabled": False,
        "invoice_emission_enabled": False,
        "lookup_enabled": False,
    }


class GreConnectionError(Exception):
    """Excepción sin secretos ni cuerpo de la respuesta externa."""


def verify_gre_oauth():
    """Comprobar únicamente que SUNAT acepta credenciales; NO emitir documentos."""
    config = gre_configuration()
    if not config["connectivity_enabled"] or not config["configured"]:
        raise GreConnectionError("La conexión GRE no está habilitada o configurada.")
    client_id = os.environ["SUNAT_GRE_CLIENT_ID"].strip()
    ruc = os.environ["SUNAT_GRE_RUC"].strip()
    user = os.environ["SUNAT_GRE_SOL_USER"].strip()
    try:
        UUID(client_id)
    except (ValueError, AttributeError) as exc:
        raise GreConnectionError("El identificador del cliente SUNAT no es válido.") from exc
    if not (ruc.isdigit() and len(ruc) == 11 and user.isalnum()):
        raise GreConnectionError("Revisa el RUC y el usuario SOL configurados.")
    body = urlencode({
        "grant_type": "password",
        "scope": GRE_SCOPE,
        "client_id": client_id,
        "client_secret": os.environ["SUNAT_GRE_CLIENT_SECRET"],
        "username": ruc + user,
        "password": os.environ["SUNAT_GRE_SOL_PASSWORD"],
    }).encode("utf-8")
    url = f"{SUNAT_TOKEN_HOST}/v1/clientessol/{client_id}/oauth2/token/"
    req = Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urlopen(req, timeout=8) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        raise GreConnectionError(
            "SUNAT no confirmó la autenticación GRE. Comprueba la configuración "
            "y la autorización de la aplicación en SOL."
        ) from exc
    if not isinstance(result, dict) or not result.get("access_token"):
        raise GreConnectionError("SUNAT no devolvió un token válido.")
    # Prohibido entregar o conservar el token al cliente.
    return {"authenticated": True, "gre_emission_enabled": False}
