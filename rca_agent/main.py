import asyncio
import logging
from config.settings import settings
from db.neo4j_client import Neo4jClient
from nats_client.subscriber import NatsSubscriber
from agent.rca_agent import main_agent
from google.adk.sessions import InMemorySessionService, Session
from google.adk.runners import Runner
from google.genai import types

# Configure logging to see NATS connection info
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') 

# Initialize Neo4j Client


# Message Handler
async def handler(data: str):
    try:
        print(f"Received alert: {data}")  
        
        # Trigger RCA pipeline
        agent = main_agent
        

        # # Run query using the Neo4j client
        # result = neo4j_client.run_query("MATCH (n) RETURN count(n) AS count")
        # node_count = result[0]["count"] if result else 0

        # print("Node count:", node_count)  
    
        # # Trigger agent execution
        print("Triggering RCA Agent...")
        import json
        import datetime
        import uuid
        
        # Setup session service and runner
        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            app_name="rca_agent",
            session_service=session_service
        )
        
        try:
            incident_data = json.loads(data)
            if not isinstance(incident_data, dict):
                incident_data = {"raw_data": incident_data}
        except Exception:
            incident_data = {"raw_data": data}
            
        state = incident_data.copy()
        state.update({
            "incident_data": incident_data,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        # Robust extraction: flatten dict to find keys regardless of nesting or case
        flat_data = {}
        def flatten(d):
            if not isinstance(d, dict): return
            for k, v in d.items():
                if isinstance(v, dict): 
                    flatten(v)
                elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    flatten(v[0]) # just grab the first item if it's a list of dicts (like alerts list)
                else: 
                    flat_data[str(k).lower().replace(" ", "_").replace("-", "_")] = v
        flatten(incident_data)
        
        failed_service = flat_data.get('failed_service') or flat_data.get('host') or flat_data.get('target') or flat_data.get('service') or 'unknown-host'
        dominant_flag = flat_data.get('dominant_flag') or flat_data.get('flag') or 'none'
        incident_id = flat_data.get('incident_id') or flat_data.get('incidentid') or str(uuid.uuid4())
        
        # Add debugging output so we can see what was actually extracted from the payload
        print(f"DEBUG EXTRACTED: failed_service={failed_service}, dominant_flag={dominant_flag}, incident_id={incident_id}")
        status_code = flat_data.get('status_code') or flat_data.get('responsecode') or flat_data.get('response_code')
        
        state['failed_service'] = failed_service
        state['dominant_flag'] = dominant_flag 
        state['incident_id'] = incident_id
        state['status_code'] = status_code
        
        await session_service.create_session(
            app_name="rca_agent",
            user_id="system",
            session_id=incident_id,
            state=state
        ) 
        
        message = f"Start RCA analysis for incident. The failed service is '{failed_service}'. The full incident data is: {json.dumps(incident_data)}"
        content = types.Content(role="user", parts=[types.Part(text=message)])
        
        async for event in runner.run_async(
            user_id="system",
            session_id=incident_id,
            new_message=content,
        ):
            print(f"RCA Agent Event Output: {event}")

    except Exception as e:
        print("Failed to process message:", e)

# Main Function
async def main():
    try:
        # Initialize NATS Subscriber
        subscriber = NatsSubscriber(settings.NATS_URL)
        await subscriber.connect()

        # Subscribe using the subscriber class
        await subscriber.subscribe(settings.NATS_SUBJECT, handler)
        
        neo4j_client = Neo4jClient(settings.NEO4J_URI, settings.NEO4J_USER, settings.NEO4J_PASSWORD , settings.NEO4J_MCP_URL,settings.NEO4J_MCP_USER , settings.NEO4J_PASSWORD)
        await neo4j_client.connect()

        print("RCA agent is running...")  

        # Keep service alive
        while True:
            await asyncio.sleep(1)

    except Exception as e:
        print("Connection failed:", e)
    finally:
        await subscriber.close()
        await neo4j_client.close()

# Run App
if __name__ == "__main__":
    asyncio.run(main())