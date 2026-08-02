"""Generate the `OTEL_EXPORTER_OTLP_HEADERS` value for Grafana Cloud.

Grafana Cloud authenticates OTLP (OpenTelemetry Protocol) traffic with HTTP
Basic auth: the username is your stack's **Instance ID** and the password is
an **API token**. This script produces the exact value to paste into Render
(or .env.production) as `OTEL_EXPORTER_OTLP_HEADERS`.

Usage:
    .venv\\Scripts\\python deploy/grafana_otlp_headers.py

It will prompt for your Instance ID and API token, then print the header.
"""

from __future__ import annotations

import base64
from getpass import getpass


def main() -> None:
    instance_id = input("Grafana Cloud Instance ID: ").strip()
    if not instance_id:
        raise SystemExit("Instance ID cannot be empty.")

    token = getpass("Grafana Cloud API token (hidden): ").strip()
    if not token:
        raise SystemExit("API token cannot be empty.")

    credentials = f"{instance_id}:{token}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")

    print("\nPaste this as OTEL_EXPORTER_OTLP_HEADERS in Render:")
    print(f"Authorization=Basic {encoded}")


if __name__ == "__main__":
    main()
