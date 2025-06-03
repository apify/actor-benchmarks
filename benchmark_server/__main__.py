import asyncio
import logging

from uvicorn import Config

from benchmark_server.benchmark_server import TestServer, app

if __name__ == "__main__":
    asyncio.run(
        TestServer(
            config=Config(
                app=app,
                lifespan="off",
                loop="asyncio",
                port=8080,
                log_config=None,
                log_level=logging.CRITICAL,
            )
        ).serve()
    )
