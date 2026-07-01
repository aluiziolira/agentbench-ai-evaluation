#!/usr/bin/env python3
"""Start the AgentBench API server with environment variables loaded."""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / ".env")

# Import and start the API
import uvicorn  # noqa: E402

from agentbench.api.app import app  # noqa: E402
from agentbench.config import get_settings  # noqa: E402

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")
