
import os
import json
import csv

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = "/Users/margento_poetry/Google Drive/My Drive/Lucia"

OUTPUT_CSV = os.path.join(
    BASE_DIR,
    "gender_statistics_after_qwen3.csv"
)

# Gender labels used in the original data
MALE_LABELS = {
    "male",
    "masculino",
    "homem",
    "mascle",
    "gizona",
}

FEMALE_LABELS = {
    "female",
    "femenino",
    "mulher",
    "femella",
    "emakume",
}

NON_BINARY_LABELS = {
    "non-binary",
    "non binary",
    "no binario",
    "no binària",
    "ezbinario",
}


# ============================================================
# FILE FILTERING
# ============================================================

def should_skip_file(filename):
    """
    Skip the original inconclusive/failed files when a corresponding
    webresolved version exists.

    Keep:
      - normal JSON files
      - *_webresolved.json
      - authors_non_male*.json

    Skip:
      - *_inconclusive.json
      - *_failed*.json

    unless the filename also contains 'webresolved'.
    """

    name = filename.lower()

    if not name.endswith(".json"):
        return True

    # Non-male files are always relevant
    if "authors_non_male" in name:
        return False

    # Web-resolved files are explicitly allowed
    if "webresolved" in name:
        return False

    # Original unresolved files should not be counted
    if "inconclusive" in name:
        return True

    if "failed" in name:
        return True

    return False


# ============================================================
# GENDER EXTRACTION
# ============================================================

def get_gender(entry):
    """
    Determine the best available gender for an author.

    Priority:
        1. Original top-level 'gender'
        2. Resolved Qwen3/web fallback gender
        3. unknown

    Important:
    The Qwen3 result is nested under:
        entry["web_fallback"]["gender"]
    """

    # --------------------------------------------------------
    # 1. Original gender
    # --------------------------------------------------------

    original_gender = entry.get("gender")

    if original_gender is not None:
        gender = str(original_gender).strip().lower()

        if gender not in {
            "",
            "unknown",
            "none",
            "null",
        }:
            return gender

    # --------------------------------------------------------
    # 2. Qwen3 / web-resolved gender
    # --------------------------------------------------------

    web_fallback = entry.get("web_fallback")

    if isinstance(web_fallback, dict):

        status = str(
            web_fallback.get("status", "")
        ).strip().lower()

        web_gender = web_fallback.get("gender")

        if web_gender is not None:
            web_gender = str(web_gender).strip().lower()

            # Only use a genuine resolved result
            if (
                status == "resolved"
                and web_gender not in {
                    "",
                    "unknown",
                    "none",
                    "null",
                }
            ):
                return web_gender

    # --------------------------------------------------------
    # 3. No usable gender
    # --------------------------------------------------------

    return "unknown"


def classify_gender(gender):
    """
    Convert the raw gender value into one of:
        male
        female
        non-binary
        unknown
    """

    gender = str(gender).strip().lower()

    if gender in MALE_LABELS:
        return "male"

    if gender in FEMALE_LABELS:
        return "female"

    if gender in NON_BINARY_LABELS:
        return "non-binary"

    return "unknown"


# ============================================================
# AUTHOR EXTRACTION
# ============================================================

def get_author_name(entry):
    """
    Extract an author's name.

    The original files use 'author'.
    """

    author = entry.get("author")

    if author is None:
        return None

    author = str(author).strip()

    if not author:
        return None

    return author


# ============================================================
# LOAD JSON
# ============================================================

def load_json_file(filepath):
    """
    Load a JSON file.

    Returns:
        list of entries
    """

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        # In case a single dictionary is stored
        if isinstance(data, dict):
            return [data]

        return []

    except Exception as e:
        print(f"ERROR reading {filepath}: {e}")
        return []


# ============================================================
# MAIN STATISTICS
# ============================================================

country_stats = []

# Global unique authors.
# IMPORTANT:
# This preserves the original script's approach:
# an author appearing in several country folders is counted
# only once in the global totals.
global_unique_authors = set()

# Store the final classified gender for global authors.
#
# The key is ONLY the author name, preserving the original
# global-deduplication approach.
#
# We do not automatically overwrite an already-established
# gender with a later conflicting result.
global_author_gender = {}

# ------------------------------------------------------------
# Find country folders
# ------------------------------------------------------------

if not os.path.isdir(BASE_DIR):
    raise FileNotFoundError(
        f"Base directory does not exist:\n{BASE_DIR}"
    )

country_folders = sorted(
    folder
    for folder in os.listdir(BASE_DIR)
    if os.path.isdir(os.path.join(BASE_DIR, folder))
)


# ============================================================
# PROCESS EACH COUNTRY
# ============================================================

for country in country_folders:

    country_path = os.path.join(BASE_DIR, country)

    # --------------------------------------------------------
    # Unique authors within this country/folder
    # --------------------------------------------------------

    country_authors = set()

    # Gender assigned to each unique author in this folder
    country_author_gender = {}

    # --------------------------------------------------------
    # Non-male sets
    # --------------------------------------------------------

    non_male_authors = set()
    non_male_1980_authors = set()
    non_male_1990_authors = set()

    # --------------------------------------------------------
    # Process files
    # --------------------------------------------------------

    for filename in sorted(os.listdir(country_path)):

        if should_skip_file(filename):
            continue

        filepath = os.path.join(country_path, filename)

        if not os.path.isfile(filepath):
            continue

        entries = load_json_file(filepath)

        filename_lower = filename.lower()

        # ----------------------------------------------------
        # Non-Male files
        # ----------------------------------------------------

        is_non_male_file = "authors_non_male" in filename_lower

        if is_non_male_file:

            if "1990" in filename_lower:
                target_set = non_male_1990_authors

            elif "1980" in filename_lower:
                target_set = non_male_1980_authors

            else:
                target_set = non_male_authors

            for entry in entries:

                if not isinstance(entry, dict):
                    continue

                author = get_author_name(entry)

                if author:
                    target_set.add(author)

            # Continue because these files are used for the
            # separate Non-Male statistics.
            continue

        # ----------------------------------------------------
        # Normal gender files
        # ----------------------------------------------------

        for entry in entries:

            if not isinstance(entry, dict):
                continue

            author = get_author_name(entry)

            if not author:
                continue

            gender = get_gender(entry)
            classification = classify_gender(gender)

            # -----------------------------------------------
            # Deduplicate within country
            # -----------------------------------------------

            if author not in country_authors:

                country_authors.add(author)
                country_author_gender[author] = classification

            else:
                # If we previously saw this author as unknown
                # but now have a usable classification, update
                # the country-level value.
                previous = country_author_gender.get(
                    author,
                    "unknown"
                )

                if previous == "unknown" and classification != "unknown":
                    country_author_gender[author] = classification

            # -----------------------------------------------
            # Global unique authors
            # -----------------------------------------------

            if author not in global_unique_authors:

                global_unique_authors.add(author)
                global_author_gender[author] = classification

            else:
                # Preserve an already-known usable classification.
                #
                # If the global value is unknown and another
                # occurrence provides a usable gender, use it.
                previous_global = global_author_gender.get(
                    author,
                    "unknown"
                )

                if (
                    previous_global == "unknown"
                    and classification != "unknown"
                ):
                    global_author_gender[author] = classification

    # ========================================================
    # COUNTRY COUNTS
    # ========================================================

    male_count = sum(
        1
        for author in country_authors
        if country_author_gender.get(author) == "male"
    )

    female_count = sum(
        1
        for author in country_authors
        if country_author_gender.get(author) == "female"
    )

    non_binary_count = sum(
        1
        for author in country_authors
        if country_author_gender.get(author) == "non-binary"
    )

    unknown_count = sum(
        1
        for author in country_authors
        if country_author_gender.get(author) == "unknown"
    )

    total_authors = len(country_authors)

    # --------------------------------------------------------
    # Percentages
    # --------------------------------------------------------

    def percentage(count, total):
        if total == 0:
            return 0.0
        return round((count / total) * 100, 2)

    # --------------------------------------------------------
    # Save country statistics
    # --------------------------------------------------------

    country_stats.append({
        "Country": country,
        "Total Authors": total_authors,

        "Male": male_count,
        "Male %": percentage(male_count, total_authors),

        "Female": female_count,
        "Female %": percentage(female_count, total_authors),

        "Non-Binary": non_binary_count,
        "Non-Binary %": percentage(
            non_binary_count,
            total_authors
        ),

        "Gender Unknown/Other": unknown_count,
        "Gender Unknown/Other %": percentage(
            unknown_count,
            total_authors
        ),

        # These remain based on the original non_male files
        "Non-Male": len(non_male_authors),
        "Non-Male 1980+": len(non_male_1980_authors),
        "Non-Male 1990+": len(non_male_1990_authors),
    })


# ============================================================
# GLOBAL STATISTICS
# ============================================================

global_total = len(global_unique_authors)

global_male = sum(
    1
    for author in global_unique_authors
    if global_author_gender.get(author) == "male"
)

global_female = sum(
    1
    for author in global_unique_authors
    if global_author_gender.get(author) == "female"
)

global_non_binary = sum(
    1
    for author in global_unique_authors
    if global_author_gender.get(author) == "non-binary"
)

global_unknown = sum(
    1
    for author in global_unique_authors
    if global_author_gender.get(author) == "unknown"
)


# ============================================================
# GLOBAL NON-MALE STATISTICS
# ============================================================
#
# These are calculated separately from the country-level
# non_male files, just as in the original approach.
#
# Because the original script uses the filename-based
# non_male files, we collect these globally by author name.
# ============================================================

global_non_male = set()
global_non_male_1980 = set()
global_non_male_1990 = set()

for country in country_folders:

    country_path = os.path.join(BASE_DIR, country)

    for filename in os.listdir(country_path):

        filename_lower = filename.lower()

        if "authors_non_male" not in filename_lower:
            continue

        filepath = os.path.join(country_path, filename)

        if not os.path.isfile(filepath):
            continue

        entries = load_json_file(filepath)

        if "1990" in filename_lower:
            target_set = global_non_male_1990

        elif "1980" in filename_lower:
            target_set = global_non_male_1980

        else:
            target_set = global_non_male

        for entry in entries:

            if not isinstance(entry, dict):
                continue

            author = get_author_name(entry)

            if author:
                target_set.add(author)


# ============================================================
# PRINT RESULTS
# ============================================================

print()
print("=" * 70)
print("GENDER STATISTICS")
print("=" * 70)

for row in country_stats:

    print()
    print(row["Country"])
    print("-" * 70)

    print(
        f"Total Authors:              "
        f"{row['Total Authors']}"
    )

    print(
        f"Male:                       "
        f"{row['Male']} ({row['Male %']}%)"
    )

    print(
        f"Female:                     "
        f"{row['Female']} ({row['Female %']}%)"
    )

    print(
        f"Non-Binary:                 "
        f"{row['Non-Binary']} ({row['Non-Binary %']}%)"
    )

    print(
        f"Gender Unknown/Other:       "
        f"{row['Gender Unknown/Other']} "
        f"({row['Gender Unknown/Other %']}%)"
    )

    print(
        f"Non-Male:                   "
        f"{row['Non-Male']}"
    )

    print(
        f"Non-Male 1980+:             "
        f"{row['Non-Male 1980+']}"
    )

    print(
        f"Non-Male 1990+:             "
        f"{row['Non-Male 1990+']}"
    )


print()
print("=" * 70)
print("GLOBAL UNIQUE AUTHORS")
print("=" * 70)

print(f"Total unique authors:       {global_total}")

print(
    f"Male:                       "
    f"{global_male} "
    f"({percentage(global_male, global_total)}%)"
)

print(
    f"Female:                     "
    f"{global_female} "
    f"({percentage(global_female, global_total)}%)"
)

print(
    f"Non-Binary:                 "
    f"{global_non_binary} "
    f"({percentage(global_non_binary, global_total)}%)"
)

print(
    f"Gender Unknown/Other:       "
    f"{global_unknown} "
    f"({percentage(global_unknown, global_total)}%)"
)

print()
print(
    f"Global Non-Male:             "
    f"{len(global_non_male)}"
)

print(
    f"Global Non-Male 1980+:       "
    f"{len(global_non_male_1980)}"
)

print(
    f"Global Non-Male 1990+:       "
    f"{len(global_non_male_1990)}"
)


# ============================================================
# WRITE CSV
# ============================================================

fieldnames = [
    "Country",
    "Total Authors",

    "Male",
    "Male %",

    "Female",
    "Female %",

    "Non-Binary",
    "Non-Binary %",

    "Gender Unknown/Other",
    "Gender Unknown/Other %",

    "Non-Male",
    "Non-Male 1980+",
    "Non-Male 1990+",
]

with open(
    OUTPUT_CSV,
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()

    for row in country_stats:
        writer.writerow(row)


print()
print("=" * 70)
print(f"CSV saved to:")
print(OUTPUT_CSV)
print("=" * 70)
