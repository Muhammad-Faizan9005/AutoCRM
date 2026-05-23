import argparse
import json
import os
from pathlib import Path
from typing import Dict, Tuple

import httpx


MAILJET_TEST_URL = "https://api.mailjet.com/v3/REST/user"
MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"


def _mask(value: str) -> str:
    if not value:
        return "(missing)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _load_env_file(env_path: Path) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        return env_vars

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_vars[key.strip()] = value.strip().strip("\"\'")
    return env_vars


def _get_mailjet_credentials() -> Tuple[str, str]:
    api_key = os.getenv("MAILJET_API_KEY") or os.getenv("MJ_APIKEY")
    secret_key = os.getenv("MAILJET_SECRET_KEY") or os.getenv("MJ_SECRET")

    if api_key and secret_key:
        return api_key, secret_key

    env_path = Path(__file__).resolve().parents[1] / ".env"
    env_vars = _load_env_file(env_path)
    api_key = api_key or env_vars.get("MAILJET_API_KEY") or env_vars.get("MJ_APIKEY") or env_vars.get("api_key")
    secret_key = (
        secret_key
        or env_vars.get("MAILJET_SECRET_KEY")
        or env_vars.get("MJ_SECRET")
        or env_vars.get("secret_key")
    )
    return api_key or "", secret_key or ""


def _send_test_email(
    client: httpx.Client,
    api_key: str,
    secret_key: str,
    sender_email: str,
    recipient_email: str,
    subject: str,
    text_body: str,
) -> bool:
    payload = {
        "Messages": [
            {
                "From": {"Email": sender_email, "Name": "AutoCRM"},
                "To": [{"Email": recipient_email}],
                "Subject": subject,
                "TextPart": text_body,
            }
        ]
    }

    response = client.post(MAILJET_SEND_URL, json=payload, auth=(api_key, secret_key))
    if response.status_code not in (200, 201):
        print(f"Send failed: HTTP {response.status_code}")
        print(response.text[:800])
        return False

    print("Send request accepted.")
    print(response.text[:800])
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Mailjet API key test and optional send.")
    parser.add_argument("--to", default="www.faizan03364869005@gmail.com", help="Recipient email address")
    parser.add_argument("--from", dest="from_email", default="", help="Sender email address")
    parser.add_argument("--subject", default="Mailjet test from AutoCRM", help="Email subject")
    parser.add_argument("--text", default="This is a Mailjet test email from AutoCRM.", help="Email text body")
    parser.add_argument("--skip-send", action="store_true", help="Only verify credentials, do not send email")
    args = parser.parse_args()

    api_key, secret_key = _get_mailjet_credentials()

    if not api_key or not secret_key:
        print("Mailjet credentials not found.")
        print("Set MAILJET_API_KEY and MAILJET_SECRET_KEY (or MJ_APIKEY/MJ_SECRET) in your environment or .env file.")
        return 1

    print(f"Using API key: {_mask(api_key)}")
    print(f"Using secret key: {_mask(secret_key)}")

    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(MAILJET_TEST_URL, auth=(api_key, secret_key))
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc}")
        return 1

    if response.status_code != 200:
        print(f"Mailjet auth failed: HTTP {response.status_code}")
        print(response.text[:500])
        return 1

    payload = response.json()
    data = payload.get("Data", []) if isinstance(payload, dict) else []

    print("Mailjet auth OK.")
    sender_email = args.from_email
    if data:
        entry = data[0]
        summary = {"ID": entry.get("ID"), "Name": entry.get("Name"), "Email": entry.get("Email")}
        print(json.dumps(summary, indent=2))
        sender_email = sender_email or entry.get("Email")
    else:
        print("Response received but no user data found.")
        sender_email = sender_email or ""

    if args.skip_send:
        return 0

    if not sender_email:
        print("Sender email is required. Provide --from or ensure Mailjet account email is available.")
        return 1

    if not args.to:
        print("Recipient email is required. Provide --to.")
        return 1

    with httpx.Client(timeout=15) as client:
        sent = _send_test_email(
            client=client,
            api_key=api_key,
            secret_key=secret_key,
            sender_email=sender_email,
            recipient_email=args.to,
            subject=args.subject,
            text_body=args.text,
        )
    return 0 if sent else 1



if __name__ == "__main__":
    raise SystemExit(main())
