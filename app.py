import streamlit as st
import pandas as pd
from graph_db import get_driver, run_query, get_raw_graph_data
# Import the new main parser functions
from parsers import run_golden_set_parsers, run_custom_parsers 
from llm import query_graph_rag, generate_report
from extractor import run_extraction
import os
import streamlit.components.v1 as components
from pyvis.network import Network
import time
import suggestions # <-- We need this for the simple engine
import mining # <-- We need this for the advanced engine
from suggestions import generate_suggestions, apply_suggestion_to_graph
from mlxtend.frequent_patterns import apriori
import glob # <-- We'll use this in the buttons now

# --- App Config ---
st.set_page_config(page_title="Certify AI - PoC", layout="wide")
st.title("🤖 Certify AI - Proof of Concept")

# --- Directory Definitions ---
PROCESSED_DIR = "processed_set"
GOLDEN_SET_DIR = "golden_set"

# --- Helper function to clear processed files ---
def clear_processed_dir():
    """Finds and deletes all files in the processed_set directory."""
    print("--- CLEARING PROCESSED_SET DIRECTORY ---")
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    files_to_delete = glob.glob(os.path.join(PROCESSED_DIR, '*'))
    for f in files_to_delete:
        try:
            os.remove(f)
            print(f"Removed {f}")
        except Exception as e:
            print(f"Error removing file {f}: {e}")

# --- Neo4j Connection ---
if 'driver' not in st.session_state:
    st.session_state.driver = get_driver()
driver = st.session_state.driver
if driver is None:
    st.error("Failed to connect to Neo4j. Please check your .env file and Neo4j Desktop.")
    st.stop()

# --- Session State for Suggestions ---
if 'suggestions' not in st.session_state:
    st.session_state.suggestions = []

# === Sidebar ===
st.sidebar.header("Controls")

# --- Workflow 1: Demo Mode ---
with st.sidebar.expander("Demo (Golden Set)"):
    st.info("Uses the local `golden_set` files for a quick demo.")
    if st.button("Load Golden Set Demo"):
        clear_processed_dir() # Clear processed files
        with st.spinner("Ingesting Golden Set..."):
            run_golden_set_parsers(driver) # Wipes and loads DB
        st.sidebar.success("Golden Set loaded!")
        st.cache_data.clear()
        st.rerun()

# --- Workflow 2: Custom Project Mode ---
with st.sidebar.expander("Custom Project (Upload & GitHub)"):
    st.info("Upload your docs and link a GitHub repo.")
    
    # File uploaders
    reg_file = st.file_uploader("1. Regulations", type=['pdf', 'docx', 'txt'])
    req_file = st.file_uploader("2. Requirements", type=['pdf', 'docx', 'txt'])
    test_file = st.file_uploader("3. Test Cases", type=['pdf', 'docx', 'txt', 'csv'])
    risk_file = st.file_uploader("4. Risks", type=['pdf', 'docx', 'txt', 'csv'])
    
    # GitHub URL
    default_url = "https://github.com/coder-rogues/certify-ai-sample-repo.git"
    github_url = st.text_input("5. Live GitHub Repo URL (.git):", default_url)

    if st.button("Process & Build Graph", type="primary"):
        clear_processed_dir() # Clear old processed files
        if not all([reg_file, req_file, test_file, risk_file, github_url]):
            st.error("Please provide all 5 inputs.")
        else:
            with st.spinner("Step 1/2: Extracting data with LLM..."):
                run_extraction(
                    output_dir=PROCESSED_DIR,
                    reg_file=reg_file,
                    req_file=req_file,
                    test_file=test_file,
                    risk_file=risk_file
                )
            
            with st.spinner(f"Step 2/2: Building graph from '{PROCESSED_DIR}' and GitHub..."):
                run_custom_parsers(driver, PROCESSED_DIR, github_url) # Wipes and loads DB
            
            st.sidebar.success("Custom project loaded!")
            st.cache_data.clear()
            st.rerun()

# === Main App ===

@st.cache_data(ttl=300) 
def run_cached_query(query, params={}):
    print(f"--- RUNNING FRESH QUERY: {query[:50]}... ---")
    return run_query(driver, query, params)

# --- 1. Audit Dashboard (Gap Analysis) ---
st.header("1. Audit & Gap Analysis")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.subheader("Test Status")
    test_data = run_cached_query("MATCH (t:Test) RETURN t.id, t.name, t.status")
    if test_data:
        st.dataframe(pd.DataFrame(test_data), width='stretch')
    else:
        st.info("No data in graph.")

with col2:
    st.subheader("Unverified Reqs")
    unverified_reqs = run_cached_query("""
        MATCH (r:Requirement) WHERE NOT (r)<-[:VERIFIES]-(:Test)
        RETURN r.id, r.text
        """)
    st.dataframe(pd.DataFrame(unverified_reqs), width='stretch')

with col3:
    st.subheader("Unimplemented Reqs")
    unimplemented_reqs = run_cached_query("""
        MATCH (r:Requirement) WHERE NOT (r)<-[:IMPLEMENTS]-(:CodeCommit)
        RETURN r.id, r.text
        """)
    st.dataframe(pd.DataFrame(unimplemented_reqs), width='stretch')

with col4:
    st.subheader("Failed Verifications")
    failed_links = run_cached_query("""
        MATCH (t:Test {status: 'FAIL'})-[:VERIFIES]->(r:Requirement)
        RETURN t.id AS test_id, r.id AS req_id
        """)
    st.dataframe(pd.DataFrame(failed_links), width='stretch')

st.divider()

# --- 2. Natural Language Query (GraphRAG) ---
st.header("2. Natural Language Query (GraphRAG)")
question = st.text_input("Ask a question about your compliance data:", 
                         placeholder="e.g., 'What test verifies requirement 002?' or 'Who implemented req 001?'")
if question:
    with st.spinner("Thinking..."):
        answer = query_graph_rag(question)
        st.success(answer)

st.divider()

# --- 3. Generative Report ---
st.header("3. Generative Report")
st.write("Select a requirement to generate a compliance summary.")

req_list = run_cached_query("MATCH (r:Requirement) RETURN r.id as id, r.text as text")
if req_list:
    req_df = pd.DataFrame(req_list).set_index('id')
    selected_req_id = st.selectbox("Choose Requirement:", options=req_df.index, format_func=lambda x: f"{x} - {req_df.loc[x, 'text']}")
    if st.button("Generate Report", key="gen_report"):
        if selected_req_id:
            with st.spinner("Gathering evidence and writing report..."):
                context_query = """
                    MATCH (req:Requirement {id: $req_id})
                    OPTIONAL MATCH (req)-[:DERIVES_FROM]->(reg:Regulation)
                    OPTIONAL MATCH (req)<-[:VERIFIES]-(test:Test)
                    OPTIONAL MATCH (req)<-[:IMPLEMENTS]-(commit:CodeCommit)
                    OPTIONAL MATCH (req)-[:MITIGATES]->(risk:Risk)
                    RETURN req, 
                           collect(DISTINCT reg) AS regulations, 
                           collect(DISTINCT test) AS tests, 
                           collect(DISTINCT commit) AS commits,
                           collect(DISTINCT risk) AS risks
                """
                context_data = run_cached_query(context_query, {'req_id': selected_req_id})
                
                if context_data:
                    report_context = str(context_data[0]) 
                    report = generate_report(report_context)
                    st.markdown(report)
                else:
                    st.error("Could not find data for this requirement.")
else:
    st.warning("No requirements found. Please load a project.")

st.divider()

# === 4. AI Suggestion Engine (The "Auditor") ===
st.header("4. AI Suggestion Engine (Auditor's Fix)")
st.info("This engine runs a simple query to find all requirements that are missing a test.")

if st.button("Find & Fix Simple Gaps"):
    with st.spinner("Step 1/2: Finding all unverified requirements..."):
        patterns = suggestions.find_unverified_req_patterns(driver)
        
    if not patterns:
        st.success("No unverified requirements found. Your project is compliant!")
    else:
        with st.spinner("Step 2/2: Generating LLM suggestions for gaps..."):
            st.session_state.suggestions = suggestions.generate_suggestions(patterns)
        st.rerun() # Rerun to display suggestions

# Display suggestions stored in session state
if st.session_state.suggestions:
    st.write(f"Found {len(st.session_state.suggestions)} compliance gaps. Suggestions:")
    
    for i in range(len(st.session_state.suggestions) - 1, -1, -1):
        s = st.session_state.suggestions[i]
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.warning(f"**Gap Found:** Requirement **{s['req_id']}** ('{s['req_text']}') is unverified.")
            st.info(f"**AI Suggestion:** Create test **{s['test_id']}** ('{s['test_name']}') and link it.")
        
        with col2:
            st.write("") # Spacer
            if st.button("✅ Approve Suggestion", key=f"approve_{i}"):
                with st.spinner(f"Applying fix for {s['req_id']}..."):
                    suggestions.apply_suggestion_to_graph(driver, s)
                    st.session_state.suggestions.pop(i)
                    st.cache_data.clear()
                st.success("Graph updated!")
                time.sleep(1)
                st.rerun()
        st.markdown("---")

st.divider()

# === 5. AI Data Mining Engine (The "Data Scientist") ===
st.header("5. AI Data Mining Engine (Data Scientist's Insight)")
st.info("This engine uses the Apriori algorithm to discover *new* patterns and exceptions.")

if st.button("Discover Gaps with Data Mining"):
    with st.spinner("Step 1/3: Extracting features from graph..."):
        df, text_map = mining.extract_features_for_mining(driver)
        
    if df.empty:
        st.warning("Mining: No data extracted from graph. Aborting.")
    else:
        st.success(f"Step 1 complete. Extracted {df.shape[0]} feature rows.")
        with st.expander("Show Extracted Features (Transaction Table)"):
            st.dataframe(df.head())

        with st.spinner("Step 2/3: Running Apriori to discover compliance rules..."):
            rules = mining.discover_rules(df) # This function is now smarter
            
            if rules.empty:
                st.info("Mining: No high-confidence rules *about testing* were discovered.")
                st.write("This can happen with small datasets. Try the 'Auditor's Fix' instead.")
                
                # --- DEBUG ---
                with st.expander("Debug: Show All Frequent Itemsets"):
                    st.write("These are all patterns the algorithm found (min_support=0.01).")
                    df_mining = df.drop(columns=['id'])
                    frequent_itemsets = apriori(df_mining, min_support=0.01, use_colnames=True)
                    st.dataframe(frequent_itemsets)
                # --- END DEBUG ---
            else:
                st.success(f"Step 2 complete. Discovered {len(rules)} rules about testing:")
                with st.expander("Discovered Association Rules (Testing Only)"):
                    st.dataframe(rules[['antecedents', 'consequents', 'support', 'confidence']])

                with st.spinner("Step 3/3: Finding exceptions to these rules..."):
                    exceptions = mining.find_exceptions(df, rules)
                    
                    if not exceptions:
                        st.success("Step 3 complete. No exceptions found! All testing rules are being followed.")
                    else:
                        st.success(f"Step 3 complete. Found {len(exceptions)} exceptions (gaps).")
                        with st.expander("Show Found Exceptions (Debug)"):
                            st.json(exceptions)
                        
                        # All exceptions are now gaps we want to fix.
                        patterns_for_llm = []
                        for exc in exceptions:
                            patterns_for_llm.append({
                                'id': exc['id'],
                                'text': text_map[exc['id']]
                            })
                        
                        st.write(f"--- Debug: Found {len(patterns_for_llm)} gaps to send to LLM for suggestions. ---")
                        
                        if patterns_for_llm:
                            st.session_state.suggestions = generate_suggestions(patterns_for_llm)
                        st.rerun()

st.divider()

# --- 6. Full Graph Data (for debugging) ---
with st.expander("Show Raw Graph Data (All Nodes)"):
    st.write("All nodes currently in the database:")
    all_data = run_cached_query("MATCH (n) RETURN labels(n) as Type, properties(n) as Data")
    if all_data:
        processed_data = []
        for item in all_data:
            row = item['Data']
            row['Type'] = item['Type'][0]
            processed_data.append(row)
        st.dataframe(pd.DataFrame(processed_data), width='stretch')
    else:
        st.info("No data in graph.")

st.divider()

# === 7. NEW: GNN SIMILARITY SEARCH ===
st.header("7. GNN Similarity Search (Data Scientist)")
st.info("This engine uses GraphSAGE embeddings (fingerprints) to find *semantically similar* items.")

# Get a list of all requirements
req_list_for_search = run_cached_query("MATCH (r:Requirement) RETURN r.id as id, r.text as text")
if req_list_for_search:
    req_df_search = pd.DataFrame(req_list_for_search).set_index('id')
    
    # 1. Select a Requirement
    selected_req_id = st.selectbox(
        "Select a Requirement to find similar items:", 
        options=req_df_search.index, 
        format_func=lambda x: f"{x} - {req_df_search.loc[x, 'text']}"
    )

    # 2. Run the Similarity Query
    if st.button("Find Similar Requirements"):
        similarity_query = """
        MATCH (r1:Requirement {id: $req_id})
        // Ensure the embedding exists before we try to use it
        WHERE r1.embedding IS NOT NULL 
        
        MATCH (r2:Requirement)
        WHERE r1 <> r2 AND r2.embedding IS NOT NULL

        // Use GDS to calculate the cosine similarity between the two vectors
        RETURN 
            r2.id AS similar_req, 
            r2.text AS text, 
            gds.similarity.cosine(r1.embedding, r2.embedding) AS similarity
        ORDER BY similarity DESC
        LIMIT 5
        """
        
        with st.spinner("Running GNN similarity search..."):
            try:
                similar_data = run_cached_query(similarity_query, {'req_id': selected_req_id})
                if similar_data:
                    st.success("Found similar requirements:")
                    st.dataframe(pd.DataFrame(similar_data), width='stretch')
                else:
                    st.warning("Could not find any similar items. Have you trained the GNN (GraphSAGE) model in Neo4j?")
            except Exception as e:
                st.error(f"GDS Error: {e}")
                st.info("Did you remember to install the GDS plugin in Neo4j Desktop and run the training pipeline from Step 2?")
else:
    st.warning("No requirements found in graph to search.")

st.divider()

# === 8. Knowledge Graph Visualization ===
st.header("8. Knowledge Graph Visualization")
st.write("Display the full knowledge graph currently in the database.")

def get_node_color(label):
    if "Requirement" in label:
        return "#FFC72C" # Yellow
    if "Regulation" in label:
        return "#DA291C" # Red
    if "Test" in label:
        return "#00B2A9" # Teal
    if "CodeCommit" in label:
        return "#005EB8" # Blue
    if "Risk" in label:
        return "#F58220" # Orange
    return "#808080" # Gray

if st.button("Generate Graph Visualization"):
    with st.spinner("Fetching graph data and building visualization..."):
        
        # 1. Fetch data
        nodes_data, edges_data = get_raw_graph_data(driver)
        st.success(f"Fetched {len(nodes_data)} nodes and {len(edges_data)} edges.")

        if not nodes_data:
            st.warning("No nodes found in the database.")
            st.stop()

        # 2. Create pyvis network
        net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white", notebook=True, cdn_resources='in_line')

        # 3. Add nodes
        added_nodes_map = {} 
        for node in nodes_data:
            node_element_id = str(node.element_id)
            node_custom_id = node.get('id', node_element_id)
            if node_element_id not in added_nodes_map:
                label = list(node.labels)[0]

                # We build a safe HTML string for the on-hover title.
                title_html = f"<b>Label:</b> {label}<br>"
                title_html += f"<b>ID:</b> {node_custom_id}<br>"
                title_html += "---<br>"
                for key, value in node.items():
                    if key != 'id':
                        safe_value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                        title_html += f"<b>{key}:</b> {safe_value}<br>"
                
                net.add_node(node_element_id, label=node_custom_id, title=title_html, color=get_node_color(label))
                added_nodes_map[node_element_id] = node_custom_id
        st.success(f"Added {len(added_nodes_map)} nodes to visualization.")

        # 4. Add edges
        edge_count = 0
        for record in edges_data:
            source_id = record['source']
            target_id = record['target']
            if source_id in added_nodes_map and target_id in added_nodes_map:
                net.add_edge(source_id, target_id, label=record['label'])
                edge_count += 1
        st.success(f"Added {edge_count} edges to visualization.")

        # 5. Generate and display HTML
        if edge_count == 0 and len(nodes_data) > 0:
             st.warning("Graph generated, but it contains 0 relationships. Displaying nodes only.")
        
        try:
            try:
                net.save_graph("temp_render.html")
            except Exception:
                pass 

            with open("graph.html", "w", encoding="utf-8") as HtmlFile:
                HtmlFile.write(net.html)
            
            with open("graph.html", "r", encoding="utf-8") as HtmlFile:
                source_code = HtmlFile.read()
                
            if source_code:
                components.html(source_code, height=800, scrolling=True)
            else:
                st.error("Generated graph.html file was empty. (net.html was empty)")
                
        except Exception as e:
            st.error(f"Error saving or reading graph.html: {e}")