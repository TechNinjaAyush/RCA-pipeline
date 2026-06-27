import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    # NATS Settings
    NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
    NATS_SUBJECT = os.getenv("NATS_SUBJECT", "pod.alert")

    # NATS Human-in-the-Loop subjects (published by Slack Bolt action handlers)
    NATS_APPROVE_SUBJECT = os.getenv("NATS_APPROVE_SUBJECT", "remediation.approved")
    NATS_REJECT_SUBJECT  = os.getenv("NATS_REJECT_SUBJECT",  "remediation.rejected")

    # Neo4j Settings
    NEO4J_URI      = os.getenv("NEO4J_URI",      "http://localhost:7687")
    NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

    # Gmail Settings (kept for backward compat, not used in Slack flow)
    GMAIL_SENDER       = os.getenv("GMAIL_SENDER",       "")
    GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
    GMAIL_RECIPIENT    = os.getenv("GMAIL_RECIPIENT",    "")

    # ── Slack Settings ────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

settings = Settings()
