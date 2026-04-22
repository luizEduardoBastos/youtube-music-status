import ytmusicapi

with open("headers.txt", "r", encoding="utf-8") as f:
    headers_raw = f.read()

ytmusicapi.setup(filepath="browser.json", headers_raw=headers_raw)

print("Browser.json created successfully!")