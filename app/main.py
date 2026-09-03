import asyncio
import logging

from app.config import Settings
from app.runner import run


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="[%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
