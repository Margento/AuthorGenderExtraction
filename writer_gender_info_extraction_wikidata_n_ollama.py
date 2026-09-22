"""
Author Metadata Extraction Pipeline

This script processes a dataset of literary works to extract and analyze author metadata,
including gender, birth year, and death year. It uses a multi-layered approach:
1. Queries Wikidata in multiple languages (en, es, ca, eu, pt-BR) for authoritative data
2. Falls back to a local LLM (Ollama with Mistral/llama3) when Wikidata fails
3. Aggregates results and performs statistical analysis on gender representation

The script is designed for research on literary funding and author demographics,
particularly focusing on Latin American and European countries.

Author: [Your Name]
License: MIT
"""

import os
import json
import time
import requests
import subprocess
from tqdm import tqdm
from collections import defaultdict
import pycountry
import re

# Configuration
EXCEL_FILE = "full_dataset.xlsx"
OUTPUT_DIR = "output"
LOG_DIR = "logs"
FAILED_AUTHORS_LOG = os.path.join(LOG_DIR, "failed_authors_log.json")
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "AuthorMetadataPipeline/1.0 (research@university.edu; Global Literary Studies Research Group)"
}

# Ensure output directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

def get_country_name(code):
    """Convert country code to full name using pycountry."""
    try:
        return pycountry.countries.get(alpha_3=code).name
    except:
        return code

def normalize_author_name(name):
    """Normalize author name from 'Last, First' format to 'First Last'."""
    if not name or not isinstance(name, str):
        return ""
    if ',' in name:
        parts = [part.strip().title() for part in name.split(',', 1)]
        return f"{parts[1]} {parts[0]}"
    return name.strip().title()

def safe_strip(val):
    """Safely strip and convert to string."""
    return str(val or "").strip()

def build_query(author_name, lang="en"):
    """Build SPARQL query for Wikidata with proper escaping."""
    # Escape quotes in author name
    escaped_name = author_name.replace('"', '\\"')
    return f"""
    SELECT ?person ?personLabel ?genderLabel ?birthDate ?deathDate WHERE {{
      ?person ?label "{escaped_name}"@{lang}.
      ?person wdt:P31 wd:Q5.  # instance of human
      OPTIONAL {{ ?person wdt:P21 ?gender. }}
      OPTIONAL {{ ?person wdt:P569 ?birthDate. }}
      OPTIONAL {{ ?person wdt:P570 ?deathDate. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang}". }}
    }}
    LIMIT 1
    """

def query_wikidata(author_name, lang="en"):
    """Query Wikidata with retry logic and error handling."""
    if '"' in author_name:
        print(f"[SKIP] Name contains quotes: {author_name}")
        return None

    query = build_query(author_name, lang)
    
    try:
        response = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": query, "format": "json"},
            headers=HEADERS,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed for '{author_name}' ({lang}): {e}")
        return None
    except json.JSONDecodeError:
        print(f"[ERROR] Invalid JSON from Wikidata for '{author_name}' ({lang}).")
        return None

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    result = bindings[0]
    return {
        "gender": result.get("genderLabel", {}).get("value"),
        "birth_year": result.get("birthDate", {}).get("value", "")[:4],
        "death_year": result.get("deathDate", {}).get("value", "")[:4]
    }

def safe_query(func, author_name, lang, retries=3, delay=5):
    """Retry a function call with exponential backoff."""
    for attempt in range(retries):
        result = func(author_name, lang=lang)
        if result is not None:
            return result
        print(f"[RETRY] Attempt {attempt + 1}/{retries} for {author_name} ({lang})")
        time.sleep(delay)
    return None

def query_wikidata_en(author_name):
    """Query Wikidata in English."""
    return safe_query(query_wikidata, author_name, lang="en")

def query_wikidata_es(author_name):
    """Query Wikidata in Spanish."""
    return safe_query(query_wikidata, author_name, lang="es")

def query_wikidata_ca(author_name):
    """Query Wikidata in Catalan."""
    return safe_query(query_wikidata, author_name, lang="ca")

def query_wikidata_eu(author_name):
    """Query Wikidata in Basque."""
    return safe_query(query_wikidata, author_name, lang="eu")

def query_wikidata_pt_BR(author_name):
    """Query Wikidata in Brazilian Portuguese."""
    return safe_query(query_wikidata, author_name, lang="pt-BR")

def query_ollama_llm(author_name, country):
    """Query local Ollama LLM for author metadata."""
    prompt = (
        f"Please provide the gender (including non-binary if applicable), year of birth, "
        f"and if applicable, year of death for the writer named '{author_name}', "
        f"who is associated with {country}. If any information is uncertain, say 'unknown'."
    )
    try:
        result = subprocess.run(
            ["ollama", "run", "llama3", prompt],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Ollama error for {author_name}: {e}")
        return "unknown"

def parse_llm_response(response_text):
    """Parse LLM response to extract gender, birth year, and death year."""
    info = {"gender": "unknown", "birth_year": None, "death_year": None}
    lines = response_text.splitlines()
    
    for line in lines:
        line = line.lower()
        if "female" in line:
            info["gender"] = "female"
        elif "male" in line:
            info["gender"] = "male"
        elif "non-binary" in line or "nonbinary" in line:
            info["gender"] = "non-binary"
        if "born" in line and any(c.isdigit() for c in line):
            for word in line.split():
                if word.isdigit() and 1800 < int(word) < 2025:
                    info["birth_year"] = word
                    break
        if "died" in line or "death" in line:
            for word in line.split():
                if word.isdigit() and 1800 < int(word) < 2025:
                    info["death_year"] = word
                    break
    return info

def save_json(data, filename):
    """Save data to JSON file with proper encoding."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def filter_non_male_authors(input_files, output_prefix="authors"):
    """Filter and analyze non-male authors from multiple input files."""
    all_data = []
    for file in input_files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                all_data.extend(json.load(f))
        except Exception as e:
            print(f"Error reading {file}: {e}")
            continue

    # Filter non-male authors
    non_male = [
        entry for entry in all_data
        if str(entry.get("gender", "")).lower() not in ["male", "masculino"]
    ]

    total = len(all_data)
    count_non_male = len(non_male)
    percent = (count_non_male / total) * 100 if total else 0

    print(f"Total authors: {total}")
    print(f"Non-male authors: {count_non_male} ({percent:.2f}%)")

    # Filter those born in or after 1980
    non_male_1980_plus = [
        entry for entry in non_male
        if entry.get("birth_year") and str(entry["birth_year"]).isdigit() and int(entry["birth_year"]) >= 1980
    ]

    # Filter those born in or after 1990
    non_male_1990_plus = [
        entry for entry in non_male_1980_plus
        if int(entry["birth_year"]) >= 1990
    ]

    # Stats
    percent_1980 = (len(non_male_1980_plus) / count_non_male) * 100 if count_non_male else 0
    percent_1990 = (len(non_male_1990_plus) / count_non_male) * 100 if count_non_male else 0

    print(f"Non-male authors born in or after 1980: {len(non_male_1980_plus)} ({percent_1980:.2f}%)")
    print(f"Non-male authors born in or after 1990: {len(non_male_1990_plus)} ({percent_1990:.2f}%)")

    # Save all three sets
    with open(f"{output_prefix}_non_male.json", "w", encoding="utf-8") as f:
        json.dump(non_male, f, indent=2, ensure_ascii=False)

    with open(f"{output_prefix}_non_male_1980_plus.json", "w", encoding="utf-8") as f:
        json.dump(non_male_1980_plus, f, indent=2, ensure_ascii=False)

    with open(f"{output_prefix}_non_male_1990_plus.json", "w", encoding="utf-8") as f:
        json.dump(non_male_1990_plus, f, indent=2, ensure_ascii=False)

    return {
        "total": total,
        "non_male": count_non_male,
        "percent": percent,
        "non_male_1980_plus": len(non_male_1980_plus),
        "non_male_1990_plus": len(non_male_1990_plus)
    }

def process_country_data(funding_source, country_name, df, output_prefix):
    """Process data for a specific country."""
    country_df = df[df['funding_country'] == funding_source]
    results_en, results_es, results_ca, results_eu, results_pt, llm_results, inconclusive = [], [], [], [], [], [], []
    processed_names = set()

    print(f"Processing {len(country_df)} authors from {country_name} ({funding_source})")
    
    for _, row in tqdm(country_df.iterrows(), total=len(country_df), desc=f"Processing {funding_source} authors"):
        raw_name = safe_strip(row.get("author_c"))
        author_name = normalize_author_name(raw_name)
        
        if not author_name or author_name in processed_names:
            continue
        processed_names.add(author_name)

        entry_metadata = {
            "author": author_name,
            "funding_country": funding_source,
            "country": country_name,
        }

        # Try Wikidata in multiple languages
        wikidata_result_en = query_wikidata_en(author_name)
        if wikidata_result_en:
            results_en.append({**entry_metadata, **wikidata_result_en, "source": "wikidata_en"})
            continue

        wikidata_result_es = query_wikidata_es(author_name)
        if wikidata_result_es:
            results_es.append({**entry_metadata, **wikidata_result_es, "source": "wikidata_es"})
            continue

        wikidata_result_ca = query_wikidata_ca(author_name)
        if wikidata_result_ca:
            results_ca.append({**entry_metadata, **wikidata_result_ca, "source": "wikidata_ca"})
            continue

        wikidata_result_eu = query_wikidata_eu(author_name)
        if wikidata_result_eu:
            results_eu.append({**entry_metadata, **wikidata_result_eu, "source": "wikidata_eu"})
            continue

        wikidata_result_pt = query_wikidata_pt_BR(author_name)
        if wikidata_result_pt:
            results_pt.append({**entry_metadata, **wikidata_result_pt, "source": "wikidata_pt-BR"})
            continue

        # Fallback to LLM
        llm_response = query_ollama_llm(author_name, country_name)
        parsed = parse_llm_response(llm_response)

        if parsed["gender"] == "unknown" and not parsed["birth_year"]:
            inconclusive.append({**entry_metadata, "llm_response": llm_response})
        else:
            llm_results.append({**entry_metadata, **parsed, "source": "llama3_local"})

    # Save results
    save_json(results_en, os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_en.json"))
    save_json(results_es, os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_es.json"))
    save_json(results_ca, os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_ca.json"))
    save_json(results_eu, os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_eu.json"))
    save_json(results_pt, os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_pt.json"))
    save_json(llm_results, os.path.join(OUTPUT_DIR, f"{output_prefix}_llm_results.json"))
    save_json(inconclusive, os.path.join(OUTPUT_DIR, f"{output_prefix}_inconclusive.json"))

    # Filter non-male authors
    filter_non_male_authors([
        os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_en.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_es.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_ca.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_eu.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_wikidata_pt.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_llm_results.json"),
        os.path.join(OUTPUT_DIR, f"{output_prefix}_inconclusive.json")
    ], output_prefix=f"{output_prefix}_non_male")

    print(f"✅ Completed processing for {country_name} ({funding_source})")

def main():
    """Main function to process all countries."""
    print("🚀 Starting author metadata extraction pipeline...")
    
    # Load the dataset
    try:
        df = pd.read_excel(EXCEL_FILE)
        print(f"✅ Loaded dataset with {len(df)} records")
    except Exception as e:
        print(f"❌ Error loading Excel file: {e}")
        return

    # Define countries to process
    countries = [
        ("URU", "Uruguay"),
        ("COL", "Colombia"),
        ("ARG", "Argentina"),
        ("CAT", "Catalonia"),
        ("MEX", "Mexico"),
        ("CHI", "Chile"),
        ("ETX", "Basque Country"),
        ("BRA", "Brazil")
    ]

    # Process each country
    for funding_source, country_name in countries:
        process_country_data(funding_source, country_name, df, funding_source.lower())

    print("\n🎉 Pipeline completed successfully!")

if __name__ == "__main__":
    main()