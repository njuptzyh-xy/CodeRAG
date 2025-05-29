from neo4j import GraphDatabase
from setting import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

AUTH = (NEO4J_USER, NEO4J_PASSWORD)

driver = GraphDatabase.driver(NEO4J_URI, auth=AUTH)