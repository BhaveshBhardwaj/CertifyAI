import os
import pypdf
import docx
import io
from llm import simple_llm_call
from security import encrypt_data

# --- 1. File Reading Utilities ---

def read_file_content(uploaded_file):
    """Reads content from an uploaded file (PDF, DOCX, TXT)."""
    if uploaded_file is None:
        return ""
        
    file_name = uploaded_file.name
    content = ""
    
    if file_name.endswith('.pdf'):
        reader = pypdf.PdfReader(io.BytesIO(uploaded_file.getvalue()))
        for page in reader.pages:
            content += page.extract_text()
    elif file_name.endswith('.docx'):
        doc = docx.Document(io.BytesIO(uploaded_file.getvalue()))
        for para in doc.paragraphs:
            content += para.text + "\n"
    elif file_name.endswith('.txt') or file_name.endswith('.csv'):
        content = uploaded_file.getvalue().decode('utf-8')
    else:
        # Fallback for other text-based files
        try:
            content = uploaded_file.getvalue().decode('utf-8')
        except UnicodeDecodeError:
            content = "Error: Could not decode file."
            
    return content

# --- 2. LLM Extraction Prompts ---

REG_PROMPT = """
You are a data extractor. Your job is to find all regulation clauses
in the following text. You must format them ONLY as:
[CLAUSE: <clause_id>] <clause_text>
Each clause must be on a new line. Do not output anything else.
"""

REQ_PROMPT = """
You are a data extractor. Your job is to find all requirements
in the following text. You must format them ONLY as:
[REQ: <req_id>] [DERIVES_FROM: <clause_id>] <requirement_text>
Each requirement must be on a new line. Do not output anything else.
"""

TEST_PROMPT = """
You are a data extractor. Your job is to find all test cases
in the following text. You must format them ONLY as a CSV with a header:
test_id,test_name,verifies_req,status
Do not output anything else.
"""

RISK_PROMPT = """
You are a data extractor. Your job is to find all risks
in the following text. You must format them ONLY as a CSV with a header:
risk_id,description,mitigated_by_req
Do not output anything else.
"""

# --- 3. Main Extractor Function ---

def run_extraction(output_dir, reg_file, req_file, test_file, risk_file):
    """
    Reads all uploaded files, runs LLM extraction, 
    and saves the formatted data to the output directory.
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # --- Read all files first ---
    print("Reading files...")
    reg_content = read_file_content(reg_file)
    req_content = read_file_content(req_file)
    test_content = read_file_content(test_file)
    risk_content = read_file_content(risk_file)
    
    # --- Run LLM extractions ---
    print("Extracting regulations...")
    extracted_regs = simple_llm_call(REG_PROMPT, reg_content)
    
    print("Extracting requirements...")
    extracted_reqs = simple_llm_call(REQ_PROMPT, req_content)
    
    print("Extracting tests...")
    extracted_tests = simple_llm_call(TEST_PROMPT, test_content)
    
    print("Extracting risks...")
    extracted_risks = simple_llm_call(RISK_PROMPT, risk_content)
    
    # --- Save extracted data ---
    print("Saving and encrypting extracted data...")
    with open(os.path.join(output_dir, 'reg.txt'), 'wb') as f:
        f.write(encrypt_data(extracted_regs))
        
    with open(os.path.join(output_dir, 'reqs.txt'), 'wb') as f:
        f.write(encrypt_data(extracted_reqs))
        
    with open(os.path.join(output_dir, 'tests.csv'), 'wb') as f:
        f.write(encrypt_data(extracted_tests))
        
    with open(os.path.join(output_dir, 'risk.csv'), 'wb') as f:
        f.write(encrypt_data(extracted_risks))
        
    print("Encryption complete.")
    return True