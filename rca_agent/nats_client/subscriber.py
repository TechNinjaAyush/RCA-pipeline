import asyncio
from nats.aio.client import Client as NATS
import logging

logger = logging.getLogger(__name__)

class NatsSubscriber:
    def __init__(self, servers):
        self.servers = servers
        self.nc = NATS()

    async def connect(self):
        try:
            await self.nc.connect(self.servers)
            logger.info(f"Connected to NATS servers: {self.servers}")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    async def subscribe(self, subject, message_handler):
        async def cb(msg):
            logger.info(f"Received a message on '{msg.subject} {msg.reply}': {msg.data.decode()}")
            # Call the provided message handler
            await message_handler(msg.data.decode())

        await self.nc.subscribe(subject, cb=cb)
        logger.info(f"Subscribed to subject: {subject}")

    async def close(self):
        if self.nc.is_connected:
            await self.nc.close()
            logger.info("NATS connection closed.")
