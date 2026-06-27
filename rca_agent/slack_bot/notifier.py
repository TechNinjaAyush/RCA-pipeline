"""
notifier.py
-----------
Public API for the RCA pipeline to post an incident card to Slack.

Responsibility: Accept structured RCA data, build the Block Kit card,
and post it via the Slack Web API. No action handling here.
"""

import logging
from typing import List, Optional

import requests

from slack_bot.blocks import build_incident_card

logger = logging.getLogger(__name__)

def post_incident_alert(
    *,
    webhook_url: str,
    incident_id: str,
    severity: str,
    namespace: str,
    failed_pod: str,
    failed_service: str,
    root_cause: str,
    diagnosis_summary: str,
    evidence: str,
    impacted_services: List[str],
    blast_radius: int,
    kubectl_command: str,
    timestamp: str,
    confidence: Optional[str] = None,
) -> dict:
    """
    Post a rich RCA incident card to Slack using a webhook.
    """
    blocks = build_incident_card(
        incident_id=incident_id,
        severity=severity,
        namespace=namespace,
        failed_pod=failed_pod,
        failed_service=failed_service,
        root_cause=root_cause,
        diagnosis_summary=diagnosis_summary,
        evidence=evidence,
        impacted_services=impacted_services,
        blast_radius=blast_radius,
        kubectl_command=kubectl_command,
        timestamp=timestamp,
        confidence=confidence,
    )

    fallback_text = (
        f"🚨 RCA Alert — {failed_service} incident detected. "
        f"Root cause: {root_cause[:100]}..."
    )

    payload = {
        "text": fallback_text,
        "blocks": blocks
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(
            "[notifier] Incident card posted via webhook — incident_id=%s",
            incident_id,
        )
        return {
            "status": "success",
            "incident_id": incident_id,
        }
    except Exception as exc:
        logger.exception("[notifier] Unexpected error posting to Slack webhook: %s", exc)
        return {"status": "error", "error": str(exc)}
