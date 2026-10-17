"""Create missing demo tokens without displaying or replacing existing secrets."""

import secrets
from pathlib import Path

from dotenv import dotenv_values


def main():
    path = Path(".env")
    text = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else Path(".env.example").read_text(encoding="utf-8")
    )
    values = dotenv_values(stream=__import__("io").StringIO(text))
    for key in ("ENGINE_SENSOR_TOKEN", "ENGINE_OPERATOR_TOKEN", "ENGINE_VIEWER_TOKEN"):
        if not values.get(key):
            token = secrets.token_urlsafe(32)
            lines = text.splitlines()
            replaced = False
            for i, line in enumerate(lines):
                if line.split("=", 1)[0].strip() == key:
                    lines[i] = key + "=" + token
                    replaced = True
            if not replaced:
                lines.append(key + "=" + token)
            text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    print("Local .env prepared. Tokens were not displayed. AI remains configured as specified in .env.")


if __name__ == "__main__":
    main()
