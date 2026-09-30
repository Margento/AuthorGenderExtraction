import json
from pathlib import Path

ROOT_DIRECTORY = Path("/Users/margento_poetry/Google Drive/My Drive/Lucia")

for folder in ROOT_DIRECTORY.iterdir():
    if not folder.is_dir():
        continue

    for file in folder.iterdir():
        if not file.name.endswith("_webresolved.json"):
            continue

        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for entry in data:
                web = entry.get("web_fallback", {})

                if web.get("gender", "").lower() not in ("", "unknown"):
                    print("\nFOLDER:", folder.name)
                    print("FILE:", file.name)
                    print("AUTHOR:", entry.get("author"))
                    print("GENDER:", web.get("gender"))
                    print("CONFIDENCE:", web.get("confidence"))
                    print("IDENTITY:", web.get("identity_confidence"))
                    print("EVIDENCE:", web.get("evidence_strength"))
                    print("STATUS:", web.get("status"))

        except Exception as e:
            print("ERROR:", file, e)