import pandas as pd
from graph_db import run_query
from mlxtend.preprocessing import TransactionEncoder
from mlxtend.frequent_patterns import apriori, association_rules

def extract_features_for_mining(driver):
    """
    "Flattens" the graph into a "transaction" table.
    Each Requirement becomes a "transaction" and its links/properties
    become "items" in its basket.
    """
    print("Mining: Extracting features from graph...")
    # This query creates a row for every requirement, checking
    # for the existence of different links.
    query = """
    MATCH (r:Requirement)
    OPTIONAL MATCH (r)<-[:VERIFIES]-(t:Test)
    OPTIONAL MATCH (r)<-[:IMPLEMENTS]-(c:CodeCommit)
    OPTIONAL MATCH (r)-[:MITIGATES]->(risk:Risk)
    RETURN 
        r.id AS id,
        r.text AS text,
        CASE WHEN t IS NOT NULL THEN 'HAS_TEST' ELSE 'NO_TEST' END AS test_status,
        CASE WHEN c IS NOT NULL THEN 'HAS_CODE' ELSE 'NO_CODE' END AS code_status,
        CASE WHEN risk IS NOT NULL THEN 'HAS_RISK' ELSE 'NO_RISK' END AS risk_status
    """
    data = run_query(driver, query)
    
    # Convert to a list of lists (transactions) for the encoder
    transactions = []
    # Keep a map of id -> text for later
    text_map = {}
    
    for record in data:
        transactions.append([
            record['test_status'],
            record['code_status'],
            record['risk_status']
        ])
        text_map[record['id']] = record['text']
        
    # Convert to a one-hot encoded DataFrame
    te = TransactionEncoder()
    te_ary = te.fit(transactions).transform(transactions)
    df = pd.DataFrame(te_ary, columns=te.columns_)
    
    # Add the 'id' column back for joining later
    df['id'] = [record['id'] for record in data]
    
    return df, text_map

def discover_rules(df):
    """
    Runs the Apriori algorithm to find frequent itemsets and
    then generates association rules *specifically* related to testing.
    """
    print("Mining: Running Apriori to find frequent itemsets...")
    df_mining = df.drop(columns=['id'])
    
    # Lowered support to catch more patterns
    frequent_itemsets = apriori(df_mining, min_support=0.01, use_colnames=True)
    
    if frequent_itemsets.empty:
        print("Mining: No frequent itemsets found.")
        return pd.DataFrame()

    print("Mining: Generating association rules...")
    # Lowered threshold to 50%
    rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=0.5)

    if rules.empty:
        print("Mining: No association rules found.")
        return pd.DataFrame()
        
    # --- THIS IS THE NEW FIX ---
    # We only care about rules that PREDICT a test.
    # We filter the rules to find ones where the 'consequent' (the 'THEN' part)
    # is 'HAS_TEST'.
    
    # 1. Convert the 'consequents' column (which is a frozenset) to a string
    rules['consequents_str'] = rules['consequents'].astype(str)
    
    # 2. Filter for rules that predict 'HAS_TEST'
    rules_about_testing = rules[rules['consequents_str'] == "frozenset({'HAS_TEST'})"]
    
    if rules_about_testing.empty:
        print("Mining: No rules were found that predict 'HAS_TEST'.")
        return pd.DataFrame()
        
    print(f"Mining: Found {len(rules_about_testing)} rules that predict 'HAS_TEST'.")
    
    return rules_about_testing

def find_exceptions(df, rules):
    """
    Finds the *exceptions* to the discovered rules.
    These are our "real" compliance gaps.
    """
    print("Mining: Finding exceptions to high-confidence rules...")
    exceptions = []
    
    for index, rule in rules.iterrows():
        # 'antecedents' are the 'IF' part (e.g., {'HAS_RISK'})
        # 'consequents' are the 'THEN' part (e.g., {'HAS_TEST'})
        
        # Convert frozensets to simple lists
        antecedents = list(rule['antecedents'])
        consequents = list(rule['consequents'])
        
        # This finds all rows in the DataFrame that HAVE the 'if' part
        # but DON'T HAVE the 'then' part. This is a rule violation.
        
        # 1. Find rows that match the antecedent
        df_antecedent = df
        for item in antecedents:
            if item in df.columns:
                df_antecedent = df_antecedent[df_antecedent[item] == True]
        
        # 2. From those, find rows that DO NOT match the consequent
        df_violation = df_antecedent
        for item in consequents:
            if item in df.columns:
                df_violation = df_violation[df_violation[item] == False]

        # These are our exceptions!
        for i, violation in df_violation.iterrows():
            exceptions.append({
                'id': violation['id'],
                'violated_rule': f"Rule: IF {antecedents} THEN {consequents}",
                'confidence': rule['confidence']
            })

    return exceptions