import re
PAT = r"(?i)OK-WW\s+v[\d.]+\s+\w+\s+-\s+OK-WW"
titles = [
    "OK-WW v3.7.4 China  - OK-WW",
    "ok-ww 断点式编排 \u2014 GUI",
    "OK-WW",
]
print("READY_TITLE_RE =", PAT)
for t in titles:
    print(f"  {t!r:40s} -> {bool(re.search(PAT, t))}")
