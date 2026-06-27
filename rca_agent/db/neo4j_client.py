from neo4j import GraphDatabase
import logging
import base64
from config.settings import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
   def __init__(self, uri, user, password ):
        self.uri = uri
        self.user = user
        self.password = password
      
        self.driver = None
        

   async def connect(self):
        try:
            
            logger.info(f"started connecteding using {self.user}")
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
