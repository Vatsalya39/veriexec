"""`python -m packages.core.service` — the core service on 127.0.0.1:8002.

Bound to the loopback interface on purpose. A demo laptop on conference Wi-Fi should not be
serving a payment-authorization API to the room, and `0.0.0.0` is one keystroke away from
doing exactly that.
"""

from __future__ import annotations

import logging

import uvicorn

from .app import HOST, PORT, create_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
