"""Собрать тестовый JSON из шаблона для проверки в Happ."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

_DEFAULT_TEMPLATE = Path("templates/balancer-vless-ws.template.json")
_PLACEHOLDERS = (
    "__UUID__",
    "__REMARKS__",
    "__USER_ID__",
    "__CLIENT_EMAIL__",
    "__CREATED_AT__",
    "__TEMPLATE_VERSION__",
)


def render_template_text(
    template: str,
    *,
    uuid: str,
    remarks: str,
    user_id: str = "0",
    client_email: str = "tg0",
    template_version: str = "preview",
) -> str:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = template
    text = text.replace("__UUID__", uuid)
    text = text.replace("__REMARKS__", remarks)
    text = text.replace("__USER_ID__", str(user_id))
    text = text.replace("__CLIENT_EMAIL__", client_email)
    text = text.replace("__CREATED_AT__", created)
    text = text.replace("__TEMPLATE_VERSION__", template_version)
    for ph in _PLACEHOLDERS:
        if ph in text:
            raise ValueError(f"Unreplaced placeholder: {ph}")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uuid", required=True, help="VLESS UUID клиента с панели")
    parser.add_argument("--remarks", default="VPN Bot test", help="Имя в Happ")
    parser.add_argument("--user-id", default="123456789")
    parser.add_argument("--email", default="tg123456789")
    parser.add_argument("--template", type=Path, default=_DEFAULT_TEMPLATE)
    parser.add_argument("--out", type=Path, help="Куда сохранить JSON")
    args = parser.parse_args()

    template = args.template.read_text(encoding="utf-8")
    rendered = render_template_text(
        template,
        uuid=args.uuid.strip(),
        remarks=args.remarks,
        user_id=args.user_id,
        client_email=args.email,
    )
    data = json.loads(rendered)
    out_text = json.dumps(data, ensure_ascii=False, indent=2)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text + "\n", encoding="utf-8")
        print(f"Written: {args.out}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()