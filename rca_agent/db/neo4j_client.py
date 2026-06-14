from neo4j import GraphDatabase
import logging
import base64
from config.settings import settings

logger = logging.getLogger(__name__)

# Create HTTP Basic Auth header using the Neo4j MCP credentials
credentials = base64.b64encode(
    f"{settings.NEO4J_MCP_USER}:{settings.NEO4J_MCP_PASSWORD}".encode()
).decode()




class Neo4jClient:
   def __init__(self, uri, user, password ,mcp_url , mcp_user,mcp_password ):
        self.uri = uri
        self.user = user
        self.password = password
        self.mcp_url = mcp_url 
        self.mcp_user  = mcp_user 
        self.mcp_password  = mcp_password
        self.driver = None
        

   async def connect(self):
        try:
            
            logger.info("started connecteding using ", self.user)
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))   
            
            
            
            logger.info("Connected to Neo4j successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

   async def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed.")

   async def run_query(self, query, parameters=None):
        if not self.driver:
            raise Exception("Driver not initialized. Call connect() first.")
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record.data() for record in result]
