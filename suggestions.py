from graph_db import run_query
from llm import get_llm_suggestion
import re

# This is our "Pattern Mining Algorithm"
# It finds all Requirement nodes that are not linked to a Test node
UNVERIFIED_REQ_PATTERN = """
MATCH (r:Requirement)
WHERE NOT (r)<-[:VERIFIES]-(:Test)
RETURN r.id AS id, r.text AS text
"""

def find_unverified_req_patterns(driver):
    """
    Runs the pattern mining query to find all unverified requirements.
    """
    print("Mining for unverified requirement patterns...")
    results = run_query(driver, UNVERIFIED_REQ_PATTERN)
    return results # Returns list of dicts: [{'id': '002', 'text': '...'}, ...]

def generate_suggestions(patterns: list):
    """
    Takes the list of unverified requirements and generates AI suggestions
    for each one.
    """
    suggestions = []
    if not patterns:
        return suggestions

    print(f"Found {len(patterns)} patterns. Generating suggestions...")
    for pattern in patterns:
        req_id = pattern['id']
        req_text = pattern['text']
        
        # Call the LLM to get a suggestion (e.g., "T-101,Test_X,PENDING")
        suggestion_csv = get_llm_suggestion(req_text)
        
        # Parse the CSV output from the LLM
        try:
            test_id, test_name, status = suggestion_csv.split(',',2)
            suggestion = {
                'req_id': req_id,
                'req_text': req_text,
                'test_id': test_id,
                'test_name': test_name,
                'status': status
            }
            suggestions.append(suggestion)
        except Exception as e:
            print(f"Error parsing LLM suggestion: {e}. Output: {suggestion_csv}")

    return suggestions

def apply_suggestion_to_graph(driver, suggestion: dict):
    """
    This is the "Supervised Feedback" step.
    The user approved, so we add the new test and link to the graph.
    """
    print(f"Applying suggestion: Creating {suggestion['test_id']}...")
    
    # 1. Create the new Test node
    run_query(driver, """
        MERGE (t:Test {id: $test_id})
        SET t.name = $test_name, t.status = $status
        """, {
            'test_id': suggestion['test_id'],
            'test_name': suggestion['test_name'],
            'status': suggestion['status']
        })

    # 2. Create the link from the Test to the Requirement
    run_query(driver, """
        MATCH (t:Test {id: $test_id})
        MATCH (r:Requirement {id: $req_id})
        MERGE (t)-[:VERIFIES]->(r)
        """, {
            'test_id': suggestion['test_id'],
            'req_id': suggestion['req_id']
        })
        
    print("Suggestion applied successfully.")