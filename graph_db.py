import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

# --- IMPORTANT ---
# Set these in a .env file in the same directory
# NEO4J_URI="bolt://localhost:7687"
# NEO4J_USER="neo4j"
# NEO4J_PASSWORD="your_password"
load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

def get_driver():
    """Establishes connection to the Neo4j database."""
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        print("Neo4j connection successful.")
        return driver
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}")
        return None

def clear_database(driver):
    """Deletes all nodes and relationships in the database."""
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("Database cleared.")

def run_query(driver, query, params={}):
    """A generic function to run a Cypher query."""
    with driver.session() as session:
        result = session.run(query, params)
        return [record.data() for record in result]

def create_graph_constraints(driver):
    """Creates unique constraints for node IDs to prevent duplicates."""
    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Regulation) REQUIRE r.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Requirement) REQUIRE r.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:CodeCommit) REQUIRE c.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Test) REQUIRE t.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Risk) REQUIRE r.id IS UNIQUE")
    print("Graph constraints ensured.")

def get_raw_graph_data(driver):
    """
    Fetches raw Node and Relationship objects from Neo4j,
    not dictionaries, for use with pyvis.
    """
    with driver.session() as session:
        # Query for all nodes
        node_result = session.run("MATCH (n) RETURN n")
        nodes = [record["n"] for record in node_result]
        
        # --- THIS IS THE CORRECTED QUERY ---
        # It MUST return elementId() for the links to work.
        edge_result = session.run("""
            MATCH (n)-[r]->(m) 
            RETURN 
                elementId(n) AS source, 
                elementId(m) AS target, 
                type(r) AS label
        """)
        edges = [record.data() for record in edge_result]
        
        return nodes, edges