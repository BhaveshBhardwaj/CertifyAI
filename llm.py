import os
from langchain_community.graphs import Neo4jGraph
from langchain_community.chains.graph_qa.cypher import GraphCypherQAChain
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser


# Initialize the LLM
# We use gpt-4 for better reasoning and Cypher generation
llm = ChatGroq(temperature=0.2, model_name="openai/gpt-oss-120b")

# Connect to the graph
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USER"),
    password=os.getenv("NEO4J_PASSWORD")
)
graph.refresh_schema()

# Create the QA chain
# This chain will take a natural language question,
# convert it to Cypher, run it, and return a natural language answer.
qa_chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    verbose=True,
    allow_dangerous_requests=True # <-- ADD THIS LINE
)

def query_graph_rag(question: str):
    """Uses the GraphRAG chain to answer a question."""
    try:
        result = qa_chain.invoke({"query": question})
        return result['result']
    except Exception as e:
        print(f"Error in RAG query: {e}")
        return "Sorry, I couldn't answer that question."

# --- Report Generation Setup ---
REPORT_PROMPT_TEMPLATE = """
You are a meticulous compliance auditor.
I will provide you with a JSON object containing all known evidence 
related to a specific requirement. Your task is to write a formal, 
narrative "Compliance Summary Report" for that single requirement.
... (rest of prompt is the same) ...
Here is the evidence:
{context}
Begin your report.
"""
REPORT_PROMPT = PromptTemplate.from_template(REPORT_PROMPT_TEMPLATE)

def generate_report(context_data: dict):
    """Uses an LLM to generate a narrative report from graph data."""
    chain = REPORT_PROMPT | llm
    try:
        report = chain.invoke({"context": context_data})
        return report.content
    except Exception as e:
        print(f"Error in report generation: {e}")
        return "Error: Could not generate report."

# --- NEW FUNCTION FOR EXTRACTOR ---

def simple_llm_call(prompt: str, content: str) -> str:
    """
    Sends a specific prompt and content to the LLM for extraction.
    """
    full_prompt = f"{prompt}\n\nHere is the document content:\n\n---\n{content}\n---"
    
    try:
        response = llm.invoke(full_prompt)
        return response.content
    except Exception as e:
        print(f"Error in simple_llm_call: {e}")
        return f"Error: Could not get response from LLM. {e}"
    
TEST_SUGGESTION_PROMPT_TEMPLATE = """
You are a senior QA engineer. You will be given a software requirement.
Your job is to generate a new, unique Test ID and a descriptive, high-level Test Name to verify this requirement.
The status of this new test should be 'PENDING'.

Requirement: "{text}"

Output your answer *only* in the following CSV format:
Test_ID,Test_Name,Status
"""

def get_llm_suggestion(text_input: str) -> str:
    """
    Calls the LLM with the test suggestion prompt.
    """
    prompt = TEST_SUGGESTION_PROMPT_TEMPLATE.format(text=text_input)
    try:
        response = llm.invoke(prompt)
        # The output should be like "T-101,Test_X,PENDING"
        return response.content.strip()
    except Exception as e:
        print(f"Error in get_llm_suggestion: {e}")
        return f"Error: Could not get response from LLM. {e}"