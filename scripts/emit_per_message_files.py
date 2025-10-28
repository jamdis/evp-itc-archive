# save as emit_per_message_files.py
import os, json

os.makedirs("site/msg", exist_ok=True)

with open("out/messages.ndjson", "r", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        out = {
            "id": d["id"],
            "subject": d["subject"],
            "author": d["author"],
            "timestamp": d["timestamp"],
            "full_text": d["full_text"],   # full body for display
        }
        with open(f"site/msg/{d['id']}.json", "w", encoding="utf-8") as o:
            json.dump(out, o, ensure_ascii=False)
print("Wrote per-message JSON files under site/msg/")
