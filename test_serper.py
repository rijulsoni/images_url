import requests as req

api_key = "3b82a79ce5636526ce0a800b1e0c36cd1b3a7a6f"
url = "https://google.serper.dev/images"

payload = {
    "q": "Ske crystal pink lemonade",
    "gl": "gb"
}

headers = {
    "X-API-KEY": api_key,
    "Content-Type": "application/json"
}

resp = req.post(url, headers=headers, json=payload, timeout=15)

print("Status:", resp.status_code)
print("Response:", resp.text)