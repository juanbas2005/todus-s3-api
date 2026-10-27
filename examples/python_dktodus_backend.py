# -*- coding: utf-8 -*-
"""Cliente del backend DK ToDus (FastAPI + MongoDB Atlas).

Descubierto analizando la app DK ToDus (Flutter APK).
Es una capa adicional sobre el S3 con:
- Autenticación por Telegram (bot @DkTodusbot)
- Anti-piratería (device_id + strikes + ban)
- Registro y listado de subidas

⚠️ VULNERABILIDAD: /api/v1/auth/verify NO valida que el usuario haya hecho
/start en el bot. Acepta cualquier temp_token + telegram_id inventado.

Uso: python python_dktodus_backend.py <command> [args]

Comandos:
  init                          → obtener temp_token
  verify <temp_token> <tg_id>   → obtener JWT
  me                            → perfil del usuario
  uploads [limit]               → lista de subidas propias
  stats                         → estadísticas globales (sin auth)
  register-device <device_id>   → registrar dispositivo
  device-status <device_id>     → estado de ban
  report-downloads <urls...>    → reportar descargas
"""
import argparse
import json
import sys

import requests

# Backend activo (probar fastapicloud.dev primero, vercel.app como fallback)
BACKEND_URL = "https://dk-todus-backend.fastapicloud.dev"
BACKEND_FALLBACK = "https://dk-todus-backend.vercel.app"


def _request(method, path, **kwargs):
    """Hace una petición al backend con fallback."""
    for base in [BACKEND_URL, BACKEND_FALLBACK]:
        try:
            url = f"{base}{path}"
            resp = requests.request(method, url, timeout=30, **kwargs)
            return resp
        except requests.RequestException as e:
            print(f"⚠️  {base} falló: {e}", file=sys.stderr)
            continue
    raise SystemExit("Todos los backends cayeron")


def cmd_init():
    """POST /api/v1/auth/init → devuelve temp_token + URL de auth."""
    resp = _request("POST", "/api/v1/auth/init",
                    headers={"Content-Type": "application/json"},
                    json={})
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def cmd_verify(temp_token, telegram_id, username=None, name=None, avatar_url=None):
    """POST /api/v1/auth/verify → intercambia temp_token por JWT."""
    body = {
        "temp_token": temp_token,
        "telegram_id": int(telegram_id),
    }
    if username:
        body["username"] = username
    if name:
        body["name"] = name
    if avatar_url:
        body["avatar_url"] = avatar_url

    resp = _request("POST", "/api/v1/auth/verify",
                    headers={"Content-Type": "application/json"},
                    json=body)
    data = resp.json()
    if "jwt_token" in data:
        print(f"JWT: {data['jwt_token']}", file=sys.stderr)
        print(data["jwt_token"])
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_me(jwt):
    """GET /api/v1/auth/me → perfil del usuario."""
    resp = _request("GET", "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {jwt}"})
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def cmd_uploads(jwt, limit=250, since_hours=24):
    """GET /api/v1/uploads → lista de subidas propias (filtrado por JWT)."""
    resp = _request("GET", f"/api/v1/uploads?limit={limit}&since_hours={since_hours}",
                    headers={"Authorization": f"Bearer {jwt}"})
    data = resp.json()
    if isinstance(data, list):
        print(f"Total: {len(data)} subidas", file=sys.stderr)
        for i, u in enumerate(data, 1):
            print(f"{i:3}. {u.get('file_name', '?')[:80]}", file=sys.stderr)
            print(f"     size: {u.get('file_size', 0)} bytes", file=sys.stderr)
            print(f"     url:  {u.get('download_url', '?')}", file=sys.stderr)
            print(f"     s3:   {u.get('s3_key', '?')}", file=sys.stderr)
            print(file=sys.stderr)
        # JSON completo a stdout
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_stats():
    """GET /api/v1/stats → estadísticas globales (sin auth)."""
    resp = _request("GET", "/api/v1/stats")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def cmd_register_device(device_id, platform="android", app_version="1.0.0", telegram_id=None):
    """POST /api/v1/devices/register → registra dispositivo."""
    body = {
        "device_id": device_id,
        "platform": platform,
        "app_version": app_version,
    }
    if telegram_id:
        body["telegram_id"] = int(telegram_id)

    resp = _request("POST", "/api/v1/devices/register",
                    headers={"Content-Type": "application/json"},
                    json=body)
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def cmd_device_status(device_id):
    """GET /api/v1/devices/status?device_id=... → estado de ban."""
    resp = _request("GET", f"/api/v1/devices/status?device_id={device_id}")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def cmd_report_downloads(device_id, urls, telegram_id=None):
    """POST /api/v1/devices/report-downloads → reporta descargas."""
    body = {
        "device_id": device_id,
        "downloads": [{"url": u} for u in urls],
    }
    if telegram_id:
        body["telegram_id"] = int(telegram_id)

    resp = _request("POST", "/api/v1/devices/report-downloads",
                    headers={"Content-Type": "application/json"},
                    json=body)
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="Cliente del backend DK ToDus")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Obtener temp_token")

    p_verify = sub.add_parser("verify", help="Intercambiar temp_token por JWT")
    p_verify.add_argument("temp_token")
    p_verify.add_argument("telegram_id", type=int)
    p_verify.add_argument("--username")
    p_verify.add_argument("--name")

    p_me = sub.add_parser("me", help="Perfil del usuario (requiere JWT)")
    p_me.add_argument("jwt")

    p_up = sub.add_parser("uploads", help="Lista de subidas propias")
    p_up.add_argument("jwt")
    p_up.add_argument("--limit", type=int, default=250)
    p_up.add_argument("--since-hours", type=int, default=24)

    sub.add_parser("stats", help="Estadísticas globales (sin auth)")

    p_rd = sub.add_parser("register-device", help="Registrar dispositivo")
    p_rd.add_argument("device_id")
    p_rd.add_argument("--platform", default="android")
    p_rd.add_argument("--app-version", default="1.0.0")
    p_rd.add_argument("--telegram-id", type=int)

    p_ds = sub.add_parser("device-status", help="Estado de ban del dispositivo")
    p_ds.add_argument("device_id")

    p_rep = sub.add_parser("report-downloads", help="Reportar descargas (anti-piratería)")
    p_rep.add_argument("device_id")
    p_rep.add_argument("urls", nargs="+")
    p_rep.add_argument("--telegram-id", type=int)

    args = p.parse_args()

    if args.cmd == "init":
        cmd_init()
    elif args.cmd == "verify":
        cmd_verify(args.temp_token, args.telegram_id, args.username, args.name)
    elif args.cmd == "me":
        cmd_me(args.jwt)
    elif args.cmd == "uploads":
        cmd_uploads(args.jwt, args.limit, args.since_hours)
    elif args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "register-device":
        cmd_register_device(args.device_id, args.platform, args.app_version, args.telegram_id)
    elif args.cmd == "device-status":
        cmd_device_status(args.device_id)
    elif args.cmd == "report-downloads":
        cmd_report_downloads(args.device_id, args.urls, args.telegram_id)


if __name__ == "__main__":
    main()
