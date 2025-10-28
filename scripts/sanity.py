
import json
n=gt200=0
for l in open('out/messages.ndjson','r',encoding='utf-8'):
    n+=1
    if len(json.loads(l)['full_text'])>200: gt200+=1
print("Total:",n,"  >200 chars:",gt200)