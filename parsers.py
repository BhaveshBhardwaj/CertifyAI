import re
import csv
import pandas as pd
import os
import shutil
import git
import io  # <-- Make sure this is imported
from graph_db import run_query
from security import decrypt_data  # <-- Import the decryption function

# --- Regex patterns ---
REG_PATTERN = re.compile(r"\[CLAUSE: (.*?)\] (.*)")
REQ_PATTERN = re.compile(r"\[REQ: (.*?)\] \[DERIVES_FROM: (.*?)\] (.*)")
COMMIT_PATTERN = re.compile(r"\[IMPLEMENTS: (.*?)\]", re.IGNORECASE)

# --- Directories ---
GOLDEN_SET_DIR = "golden_set"
PROCESSED_DIR = "processed_set"
TEMP_REPO_DIR = "temp_repo_clone"  # For remote clones

# === Universal Parser Functions ===
# These parsers now decrypt the files from the data_dir

def parse_regs(driver, data_dir):
    file_path = os.path.join(data_dir, 'reg.txt')
    try:
        # 1. Read as bytes
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
        
        # 2. Decrypt content
        decrypted_content = decrypt_data(encrypted_data)
        
        # 3. Parse the decrypted string
        for line in decrypted_content.splitlines():
            match = REG_PATTERN.match(line)
            if match:
                clause_id, text = match.groups()
                run_query(driver, 
                          "MERGE (r:Regulation {id: $id}) SET r.text = $text", 
                          {'id': clause_id, 'text': text})
        print(f"Parsed Regulations from {data_dir}")
    except FileNotFoundError:
        print(f"Warning: {file_path} not found. Skipping regulations.")
    except Exception as e:
        print(f"Error parsing regulations: {e}")

def parse_reqs(driver, data_dir):
    file_path = os.path.join(data_dir, 'reqs.txt')
    try:
        # 1. Read as bytes
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()

        # 2. Decrypt content
        decrypted_content = decrypt_data(encrypted_data)
        
        # 3. Parse the decrypted string
        for line in decrypted_content.splitlines():
            match = REQ_PATTERN.match(line)
            if match:
                req_id, reg_id, text = match.groups()
                run_query(driver, 
                          "MERGE (r:Requirement {id: $id}) SET r.text = $text", 
                          {'id': req_id, 'text': text})
                run_query(driver, """
                    MATCH (req:Requirement {id: $req_id})
                    MATCH (reg:Regulation {id: $reg_id})
                    MERGE (req)-[:DERIVES_FROM]->(reg)
                    """, {'req_id': req_id, 'reg_id': reg_id})
        print(f"Parsed Requirements from {data_dir}")
    except FileNotFoundError:
        print(f"Warning: {file_path} not found. Skipping requirements.")
    except Exception as e:
        print(f"Error parsing requirements: {e}")

def parse_tests(driver, data_dir):
    file_path = os.path.join(data_dir, 'tests.csv')
    try:
        # 1. Read as bytes
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
            
        # 2. Decrypt content
        decrypted_content = decrypt_data(encrypted_data)
        
        # 3. Use io.StringIO to treat the decrypted string as a file
        file_like_object = io.StringIO(decrypted_content)
        
        reader = csv.DictReader(file_like_object)
        for row in reader:
            run_query(driver, """
                MERGE (t:Test {id: $id}) 
                SET t.name = $name, t.status = $status
                """, {'id': row['test_id'], 'name': row['test_name'], 'status': row['status']})
            run_query(driver, """
                MATCH (t:Test {id: $test_id})
                MATCH (req:Requirement {id: $req_id})
                MERGE (t)-[:VERIFIES]->(req)
                """, {'test_id': row['test_id'], 'req_id': row['verifies_req']})
        print(f"Parsed Tests from {data_dir}")
    except FileNotFoundError:
        print(f"Warning: {file_path} not found. Skipping tests.")
    except Exception as e:
        print(f"Error parsing tests: {e}")

def parse_risks(driver, data_dir):
    file_path = os.path.join(data_dir, 'risk.csv')
    try:
        # 1. Read as bytes
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
        
        # 2. Decrypt content
        decrypted_content = decrypt_data(encrypted_data)
        
        # 3. Use io.StringIO to treat the decrypted string as a file
        file_like_object = io.StringIO(decrypted_content)
        
        reader = csv.DictReader(file_like_object)
        for row in reader:
            run_query(driver, """
                MERGE (r:Risk {id: $id}) 
                SET r.description = $desc
                """, {'id': row['risk_id'], 'desc': row['description']})
            run_query(driver, """
                MATCH (r:Risk {id: $risk_id})
                MATCH (req:Requirement {id: $req_id})
                MERGE (req)-[:MITIGATES]->(r)
                """, {'risk_id': row['risk_id'], 'req_id': row['mitigated_by_req']})
        print(f"Parsed Risks from {data_dir}")
    except FileNotFoundError:
        print(f"Warning: {file_path} not found. Skipping risks.")
    except Exception as e:
        print(f"Error parsing risks: {e}")

# === Git Parser Functions ===
# (These do not change, as they don't read from the encrypted folder)

def _parse_commits(driver, repo_object):
    """Internal function to read commits from an active repo object."""
    for commit in repo_object.iter_commits():
        match = COMMIT_PATTERN.search(commit.message)
        if match:
            req_id = match.group(1)
            commit_id = commit.hexsha
            run_query(driver, """
                MERGE (c:CodeCommit {id: $id}) 
                SET c.message = $msg, c.author = $author
                """, {'id': commit_id, 'msg': commit.message, 'author': str(commit.author)})
            run_query(driver, """
                MATCH (c:CodeCommit {id: $commit_id})
                MATCH (req:Requirement {id: $req_id})
                MERGE (c)-[:IMPLEMENTS]->(req)
                """, {'commit_id': commit_id, 'req_id': req_id})
    print("Parsed Git Commits.")

def parse_git_remote(driver, repo_url):
    """Clones a remote repo, parses it, and deletes it."""
    if os.path.exists(TEMP_REPO_DIR):
        print(f"Removing old temp repo: {TEMP_REPO_DIR}")
        def del_rw(action, name, exc):
            os.chmod(name, 0o777)
            os.remove(name)
        shutil.rmtree(TEMP_REPO_DIR, onerror=del_rw)
    try:
        print(f"Cloning {repo_url}...")
        repo = git.Repo.clone_from(repo_url, TEMP_REPO_DIR)
        _parse_commits(driver, repo)
    except Exception as e:
        print(f"ERROR: Could not clone or parse remote repo: {e}")

def parse_git_local(driver, repo_path):
    """Parses a local repo."""
    try:
        repo = git.Repo(repo_path)
        _parse_commits(driver, repo)
    except Exception as e:
        print(f"ERROR: Could not parse local repo at {repo_path}: {e}")

# === Main Entry Points ===
# (These do not change)

def run_golden_set_parsers(driver):
    """Workflow 1: Clears DB and runs all parsers on the local 'golden_set'."""
    # NOTE: This workflow will now FAIL unless you manually
    # encrypt the golden_set files with your SECRET_KEY.
    from graph_db import clear_database, create_graph_constraints
    print("--- RUNNING GOLDEN SET WORKFLOW ---")
    clear_database(driver)
    create_graph_constraints(driver)
    
    parse_regs(driver, GOLDEN_SET_DIR)
    parse_reqs(driver, GOLDEN_SET_DIR)
    parse_tests(driver, GOLDEN_SET_DIR)
    parse_risks(driver, GOLDEN_SET_DIR)
    parse_git_local(driver, os.path.join(GOLDEN_SET_DIR, 'sample_code_repo'))
    
    print("\n--- Golden Set ingested successfully! ---")

def run_custom_parsers(driver, data_dir, repo_url):
    """Workflow 2: Clears DB and runs parsers on custom data."""
    from graph_db import clear_database, create_graph_constraints
    print("--- RUNNING CUSTOM PROJECT WORKFLOW ---")
    clear_database(driver)
    create_graph_constraints(driver)
    
    parse_regs(driver, data_dir)
    parse_reqs(driver, data_dir)
    parse_tests(driver, data_dir)
    parse_risks(driver, data_dir)
    parse_git_remote(driver, repo_url)
    
    print("\n--- Custom Project ingested successfully! ---")