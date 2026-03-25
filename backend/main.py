from __future__ import annotations

import uvicorn

from app.api import create_app
from app.config import APP_HOST, APP_PORT, LOG_LEVEL

app = create_app()


def main() -> int:
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level=LOG_LEVEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
