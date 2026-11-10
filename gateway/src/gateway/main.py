from __future__ import annotations

import logging
import os
import sys

import uvicorn

from gateway.config import GatewaySettings


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = GatewaySettings.from_env()
    except ValueError as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        sys.exit(2)
    from gateway.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
