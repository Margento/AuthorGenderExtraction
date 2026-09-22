import os
import json
import csv
from pathlib import Path
from collections import defaultdict

def calculate_author_stats(root_folder):
    global_unique_authors = set()
    global_failed_inconclusive = set()
    folder_stats = {}

    items = os.listdir(root_folder)
    for item in items:
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path):
            folder_unique_authors = set()
            folder_failed_inconclusive = set()
            
            for file in os.listdir(item_path):
                if not file.endswith(".json"):
                    continue
                file_path = os.path.join(item_path, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if not isinstance(data, list): continue
                        for entry in data:
                            author = entry.get("author")
                            if not author: continue
                            folder_unique_authors.add(author)
                            if "failed" in file.lower() or "inconclusive" in file.lower():
                                folder_failed_inconclusive.add(author)
                except (json.JSONDecodeError, IOError):
                    continue

            total_count = len(folder_unique_authors)
            fail_count = len(folder_failed_inconclusive)
            fail_percent = (fail_count / total_count * 100) if total_count > 0 else 0
            
            folder_stats[item] = {
                "Total Unique": total_count,
                "Failed/Inconclusive": fail_count,
                "Percentage": f"{fail_percent:.2f}%"
            }
            global_unique_authors.update(folder_unique_authors)
            global_failed_inconclusive.update(folder_failed_inconclusive)

    global_total = len(global_unique_authors)
    global_fail = len(global_failed_inconclusive)
    global_percent = f"{(global_fail / global_total * 100):.2f}%" if global_total > 0 else "0.00%"

    return folder_stats, global_total, global_fail, global_percent

def save_results(folder_stats, g_total, g_fail, g_percent):
    """Saves results to CSV (for Google Docs/Sheets) and TXT (for records)."""
    
    # 1. Save to CSV
    csv_filename = "inconclusive_plus_failed_author_metadata_stats.csv"
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # Header
        writer.writerow(["Folder", "Total Unique", "Failed/Inconclusive", "Percentage"])
        
        # Data rows
        for folder, stats in folder_stats.items():
            writer.writerow([folder, stats["Total Unique"], stats["Failed/Inconclusive"], stats["Percentage"]])
        
        # Global Total row
        writer.writerow(["GLOBAL TOTAL", g_total, g_fail, g_percent])

    # 2. Save to a clean Text file
    txt_filename = "inconclusive_plus_failed_author_metadata_report.txt"
    with open(txt_filename, 'w', encoding='utf-8') as txtfile:
        txtfile.write("AUTHOR METADATA EXTRACTION REPORT\n")
        txtfile.write("="*60 + "\n")
        txtfile.write(f"{'Folder':<20} | {'Total Unique':<15} | {'Failed/Incon':<15} | {'% Fail':<10}\n")
        txtfile.write("-" * 65 + "\n")
        for folder, stats in folder_stats.items():
            txtfile.write(f"{folder:<20} | {stats['Total Unique']:<15} | {stats['Failed/Inconclusive']:<15} | {stats['Percentage']:>8}\n")
        txtfile.write("-" * 65 + "\n")
        txtfile.write(f"{'GLOBAL TOTAL':<20} | {g_total:<15} | {g_fail:<15} | {g_percent:>8}\n")

    print(f"✅ Results saved to {csv_filename} and {txt_filename}")

if __name__ == "__main__":
    ROOT_DIRECTORY = Path("/Users/Raluca/Google Drive/My Drive/Lucia") 
    stats, total, fail, percent = calculate_author_stats(ROOT_DIRECTORY)
    save_results(stats, total, fail, percent)
