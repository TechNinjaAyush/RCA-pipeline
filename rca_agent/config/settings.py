import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    # NATS Settings
    NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
    NATS_SUBJECT = os.getenv("NATS_SUBJECT", "pod.alert")
    
    # Neo4j Settings
    NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://f2ff6262.databases.neo4j.io")
    NEO4J_USER = os.getenv("NEO4J_USER", "f2ff6262")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "FmbJEXbjENuu6W5uwsUV80aCb2z356y0vEKJU3SqKPI")

    # Neo4j MCP Settings
    NEO4J_MCP_URL = os.getenv("NEO4J_MCP_URL", "http://localhost:8043/mcp")
    NEO4J_MCP_USER = os.getenv("NEO4J_MCP_USER", "f2ff6262")
    NEO4J_MCP_PASSWORD = os.getenv("NEO4J_MCP_PASSWORD", "FmbJEXbjENuu6W5uwsUV80aCb2z356y0vEKJU3SqKPI")

    # Gmail Settings
    GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
    GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
    GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT", "")

settings = Settings()
