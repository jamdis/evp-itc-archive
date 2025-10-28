# build_lunr_single.py
import json, os
from lunr import lunr

# 1) Load NDJSON
rows = []
with open("out/messages.ndjson", "r", encoding="utf-8") as f:
    for line in f:
        rows.append(json.loads(line))

# 2) Build index (no tuples in fields)
idx = lunr(
    ref="id",
    fields=("subject", "author", "index_text"),
    documents=rows
)

# 3) Save index + lightweight doc lookup
os.makedirs("site", exist_ok=True)
with open("site/lunr_index.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(idx.serialize(), ensure_ascii=False))

with open("site/docs.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(
        [
            {
                "id": d["id"],
                "subject": d["subject"],
                "author": d["author"],
                "timestamp": d["timestamp"],
                "year": d["year"]
            }
            for d in rows
        ],
        ensure_ascii=False
    ))
print("Wrote site/lunr_index.json and site/docs.json")
