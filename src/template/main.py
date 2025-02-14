"""
Applicant Main File.
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from template.asgi import get_application

# Load environment variables from .env file
load_dotenv()


app: FastAPI = get_application()


if __name__ == "__main__":
    # pylint: disable=wrong-import-position
    import uvicorn

    # pylint: disable=ungrouped-imports
    from template.settings.uvicorn_settings import UvicornSettings

    settings = UvicornSettings()

    uvicorn.run(
        "template.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
    )
