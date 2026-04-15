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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
