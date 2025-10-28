# EVP-ITC Yahoo Group Archive

Static, searchable archive of the Yahoo Group **evp-itc**.  The  Yahoo Group EVP-ITC contained experiments related to electronic voice phenomena, including writings by Frank Sumption, inventor of the "Frank's Box" AKA the "Spirit Box".  When Yahoo Groups shut down in 2020, many groups were archived by Archive Team on the Internet Archive, but these archives are not in a format that is easily read or searched.

The purpose of this project is to make these experimenter's records available on the web. The scripts here could probably be easily repurposed to create a searchable site from any Yahoo Group that was archived, but this hasn't been tested.

Everything here has been pretty terribly vibe coded.  

## What’s here
- `scripts/` These scripts ingest a WARC, converting it to NDJSON and then a Lunr index, and a file for each message with a simple web page for searching it all. So:  WARC ➜ NDJSON ➜ Lunr index ➜ static files
- `site/` — static site (index + search); per-message JSON generated under `site/msg/`
- `data/` — local-only source WARCs (ignored by this repository, but you can download them yoursef from IA. )

## Build (local)
```bash
python scripts/extract_from_rawemail_only.py data/evp-itc.EqK0pyt.warc.gz
python scripts/build_lunr_single.py
python scripts/emit_per_message_files.py
# serve on a local webserver
cd site && python -m http.server 8000
