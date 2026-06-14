import sys
import os
import json
from neo4j import GraphDatabase 
import asyncio
from nats.aio.client import Client as NATS
import logging


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.settings import settings

def read_neo4j_cypher(query: str) -> str:
    """Executes a read Cypher query on the Neo4j database.
    
    Args:
        query: The Cypher query to execute.
        
    Returns:
        JSON string of the query results.
    """
    
    print(f"neo4j user is:{settings.NEO4J_URI}and password is :{settings.NEO4J_PASSWORD}") 
    
    
    
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    try:
        def read_tx(tx):
            result = tx.run(query)
            return [record.data() for record in result]
            
        with driver.session() as session:
            records = session.execute_read(read_tx)
            
        return json.dumps(records, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        driver.close()





async def check_pod_status_via_nats(pod_name: str) -> str:
    """Asks the external Observer via NATS for the status of a specific pod.
    
    Args:
        pod_name: The name of the failed pod.
        
    Returns:
        JSON string of the pod status, or an error/timeout message.
    """
    nc = NATS()
    try:
        # Connect to NATS using the global settings
        await nc.connect(settings.NATS_URL)
        
        # Publish request and wait up to 5 seconds for the Observer to reply
        request_data = json.dumps({"action": "check_pod", "pod_name": pod_name})
        msg = await nc.request("observer.pod.status", request_data.encode(), timeout=5.0)
        
        return msg.data.decode()
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Timeout: The Observer service did not reply with the status for pod {pod_name}. Assume it might be scaled to zero or the observer is down."})
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        await nc.close()

async def fetch_pod_logs_via_nats(pod_name: str) -> str:
    """Asks the external Observer via NATS for the logs of a specific pod.
    
    Args:
        pod_name: The name of the failed pod.
        
    Returns:
        JSON string containing the recent logs of the pod, or an error/timeout message.
    """
    nc = NATS()
    try:
        # Connect to NATS using the global settings
        await nc.connect(settings.NATS_URL)
        
        # Publish request and wait up to 10 seconds for the Observer to reply (fetching logs might take longer)
        request_data = json.dumps({"action": "fetch_logs", "pod_name": pod_name})
        msg = await nc.request("observer.pod.logs", request_data.encode(), timeout=10.0)
        
        return msg.data.decode()
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Timeout: The Observer service did not reply with logs for pod {pod_name}."})
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        await nc.close()



def get_current_time() -> str:
    """Returns the current date and time in ISO 8601 format."""
    from datetime import datetime
    return datetime.now().isoformat()

def send_email_via_gmail(report_content: str) -> str:
    """Sends the RCA report via Gmail using SMTP.
    
    Args:
        report_content: The formatted RCA report.
        
    Returns:
        A success or error message.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender = settings.GMAIL_SENDER
    password = settings.GMAIL_APP_PASSWORD
    recipient = settings.GMAIL_RECIPIENT

    if not sender or not password or not recipient:
        return json.dumps({"error": "Gmail credentials or recipient are not configured in .env"})

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = "Automated RCA Report"
    
    msg.attach(MIMEText(report_content, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return json.dumps({"status": "success", "message": f"Email successfully sent to {recipient}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to send email: {str(e)}"})
