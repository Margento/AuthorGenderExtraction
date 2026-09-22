import os
import json
import csv
from pathlib import Path


def calculate_advanced_stats(root_folder):
    MALE_LABELS = {"male", "masculino", "homem", "mascle", "gizona"}
    FEMALE_LABELS = {"female", "femenino", "mulher", "femella", "emakume"}
    NON_BINARY_LABELS = {"non-binary", "non binary", "no binario", "no binària", "ezbinario"}

    global_unique_authors = set()
    global_non_male = set()
    global_non_male_1980 = set()
    global_non_male_1990 = set()
    global_non_binary_explicit = set()
    global_gender_unknown_or_other = set()

    folder_stats = {}

    items = os.listdir(root_folder)
    for item in items:
        item_path = os.path.join(root_folder, item)
        if not os.path.isdir(item_path):
            continue
        
        folder_unique = set()
        folder_non_male = set()
        folder_non_male_1980 = set()
        folder_non_male_1990 = set()
        folder_non_binary_explicit = set()
        folder_gender_unknown_or_other = set()

        # --- STEP 1: CONTENT SCAN (Gender & Total Unique) ---
        for file in os.listdir(item_path):
            if not file.endswith(".json"): continue
            file_path = os.path.join(item_path, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, list): continue
                    for entry in data:
                        author = entry.get("author")
                        if not author: continue
                        folder_unique.add(author)
                        
                        gender_val = str(entry.get("gender", "")).lower().strip()
                        if any(label in gender_val for label in NON_BINARY_LABELS):
                            folder_non_binary_explicit.add(author)
                        elif (not gender_val or 
                              (gender_val not in MALE_LABELS and 
                               gender_val not in FEMALE_LABELS and 
                               not any(label in gender_val for label in NON_BINARY_LABELS))):
                            folder_gender_unknown_or_other.add(author)
            except: continue

        # --- STEP 2: FILE SCAN (Non-Male Cohorts) ---
        for file in os.listdir(item_path):
            if not file.endswith(".json"): continue
            file_path = os.path.join(item_path, file)
            
            # We look for files that are specifically the 'non_male' filtered lists
            if "authors" in file.lower() and "non_male" in file.lower():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if not isinstance(data, list): continue
                        for entry in data:
                            author = entry.get("author")
                            if not author: continue
                            
                            # Logic for cohorts
                            is_1990 = "1990" in file
                            is_1980 = "1980" in file and "1990" not in file
                            is_general = "1980" not in file and "1990" not in file
                            
                            if is_general:
                                folder_non_male.add(author)
                            if is_1980:
                                folder_non_male_1980.add(author)
                                folder_non_male.add(author) # Safety: 1980s are also non-male
                            if is_1990:
                                folder_non_male_1990.add(author)
                                folder_non_male.add(author) # Safety: 1990s are also non-male
                except: continue

        total = len(folder_unique)
        folder_stats[item] = {
            "Total": total,
            "Non-Male": len(folder_non_male),
            "Non-Male 1980+": len(folder_non_male_1980),
            "Non-Male 1990+": len(folder_non_male_1990),
            "Non-Binary (Explicit)": len(folder_non_binary_explicit),
            "Gender Unknown/Other": len(folder_gender_unknown_or_other)
        }

        global_unique_authors.update(folder_unique)
        global_non_male.update(folder_non_male)
        global_non_male_1980.update(folder_non_male_1980)
        global_non_male_1990.update(folder_non_male_1990)
        global_non_binary_explicit.update(folder_non_binary_explicit)
        global_gender_unknown_or_other.update(folder_gender_unknown_or_other)

    g_total = len(global_unique_authors)
    global_results = {
        "Total": g_total,
        "Non-Male": len(global_non_male),
        "Non-Male 1980+": len(global_non_male_1980),
        "Non-Male 1990+": len(global_non_male_1990),
        "Non-Binary (Explicit)": len(global_non_binary_explicit),
        "Gender Unknown/Other": len(global_gender_unknown_or_other)
    }

    return folder_stats, global_results

def save_advanced_results(folder_stats, global_results):
    csv_filename = "unknown_n_non-binary_gender_stats_wiki_n_llama3_1.csv"
    columns = ["Folder", "Total", "Non-Male", "Non-Male 1980+", "Non-Male 1990+", "Non-Binary (Explicit)", "Gender Unknown/Other"]
    
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(columns)
        for folder, stats in folder_stats.items():
            total = stats["Total"]
            row = [folder]
            for col in columns[1:]:
                val = stats[col]
                perc = (val / total * 100) if total > 0 else 0
                row.append(f"{val} ({perc:.2f}%)")
            writer.writerow(row)
        
        g_total = global_results["Total"]
        global_row = ["GLOBAL TOTAL"]
        for col in columns[1:]:
            val = global_results[col]
            perc = (val / g_total * 100) if g_total > 0 else 0
            global_row.append(f"{val} ({perc:.2f}%)")
        writer.writerow(global_row)

    print(f"✅ Corrected advanced stats saved to {csv_filename}")

if __name__ == "__main__":
    ROOT_DIRECTORY = Path("/Users/Raluca/Google Drive/My Drive/Lucia") 
    stats, global_res = calculate_advanced_stats(ROOT_DIRECTORY)
    save_advanced_results(stats, global_res)