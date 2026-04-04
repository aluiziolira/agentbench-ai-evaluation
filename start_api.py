#!/usr/bin/env python3
"""Start the AgentBench API server with environment variables loaded."""

import os
import sys

# Add project to path
sys.path.insert(0, "/home/aluizio/aluizio-projects/agentbench-ai-evaluation")

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv("/home/aluizio/aluizio-projects/agentbench-ai-evaluation/.env")

# Import and start the API
import uvicorn
from agentbench.api.app import app

if __name__ == "__main__":
    print(f"Starting API with MONGODB_URI={os.environ.get('MONGODB_URI', 'NOT SET')}")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
