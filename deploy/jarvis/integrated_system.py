"""
JARVIS-OS Integrated System Entry Point
This module serves as the main entry point for the JARVIS-OS application.
"""

import os
import sys
import asyncio
import signal
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health import app as health_app
from metrics import create_metrics_app, set_app_state

# Configure logging
logging.basicConfig(
    level=os.getenv("JARVIS_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("jarvis.integrated_system")


class JarvisApplication:
    """Main JARVIS-OS application orchestrator."""

    def __init__(self):
        self.health_app = health_app
        self.metrics_app = None
        self.main_app = None
        self._shutdown_event = asyncio.Event()

    def create_main_app(self) -> FastAPI:
        """Create the main FastAPI application with all routes."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            logger.info("Starting JARVIS-OS Integrated System...")
            set_app_state("running")

            # Initialize core components
            await self._initialize_components()

            logger.info("JARVIS-OS Integrated System started successfully")
            yield

            # Shutdown
            logger.info("Shutting down JARVIS-OS Integrated System...")
            set_app_state("stopping")
            await self._shutdown_components()
            logger.info("JARVIS-OS Integrated System stopped")

        app = FastAPI(
            title="JARVIS-OS",
            description="JARVIS Operating System - AI Agent Platform",
            version=os.getenv("JARVIS_VERSION", "1.0.0"),
            lifespan=lifespan,
            docs_url="/docs" if os.getenv("JARVIS_ENVIRONMENT") != "production" else None,
            redoc_url="/redoc" if os.getenv("JARVIS_ENVIRONMENT") != "production" else None,
        )

        # CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=os.getenv("JARVIS_CORS_ORIGINS", "*").split(","),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Mount health endpoints
        app.mount("/health", self.health_app)

        # Mount metrics app
        self.metrics_app = create_metrics_app()
        app.mount("/metrics", self.metrics_app)

        # Core API routes
        @app.get("/")
        async def root():
            return {
                "name": "JARVIS-OS",
                "version": os.getenv("JARVIS_VERSION", "1.0.0"),
                "status": "running",
                "environment": os.getenv("JARVIS_ENVIRONMENT", "production"),
            }

        @app.get("/api/v1/status")
        async def status():
            return {
                "status": "operational",
                "components": {
                    "health": "healthy",
                    "metrics": "healthy",
                    "agents": "initialized",
                },
            }

        # Agent management endpoints (placeholders for actual implementation)
        @app.post("/api/v1/agents/spawn")
        async def spawn_agent(agent_config: dict):
            """Spawn a new agent."""
            # TODO: Implement actual agent spawning
            return {"status": "accepted", "agent_id": "agent-" + os.urandom(8).hex()}

        @app.get("/api/v1/agents")
        async def list_agents():
            """List active agents."""
            # TODO: Implement actual agent listing
            return {"agents": []}

        @app.post("/api/v1/tasks")
        async def submit_task(task: dict):
            """Submit a task for processing."""
            # TODO: Implement actual task submission
            return {"status": "queued", "task_id": "task-" + os.urandom(8).hex()}

        @app.get("/api/v1/tasks/{task_id}")
        async def get_task(task_id: str):
            """Get task status."""
            # TODO: Implement actual task status
            return {"task_id": task_id, "status": "pending"}

        return app

    async def _initialize_components(self):
        """Initialize all system components."""
        # Initialize database connections, agent pools, etc.
        logger.info("Initializing core components...")

        # Placeholder for actual initialization
        await asyncio.sleep(0.1)

        logger.info("Core components initialized")

    async def _shutdown_components(self):
        """Gracefully shutdown all components."""
        logger.info("Shutting down components...")

        # Placeholder for actual shutdown
        await asyncio.sleep(0.1)

        logger.info("Components shut down")

    def run(self):
        """Run the application."""
        self.main_app = self.create_main_app()

        # Configuration
        host = os.getenv("JARVIS_API_HOST", "0.0.0.0")
        port = int(os.getenv("JARVIS_API_PORT", "8000"))
        workers = int(os.getenv("JARVIS_API_WORKERS", "1"))  # 1 for container, >1 for bare metal

        logger.info(f"Starting server on {host}:{port} with {workers} worker(s)")

        # Run with uvicorn
        uvicorn.run(
            self.main_app,
            host=host,
            port=port,
            workers=workers,
            log_level=os.getenv("JARVIS_LOG_LEVEL", "info").lower(),
            access_log=True,
            use_colors=False,
        )


def main():
    """Main entry point."""
    app = JarvisApplication()
    app.run()


if __name__ == "__main__":
    main()