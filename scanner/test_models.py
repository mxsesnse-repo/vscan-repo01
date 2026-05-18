import urllib.request
import json

api_key = "AIzaSyA72guuplP6PobWRLUE-qI6spIV4NxEtDk"
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print("YOUR AVAILABLE MODELS:")
        print("-" * 20)
        for model in data.get('models', []):
            # Only print models that support generateContent
            if 'generateContent' in model.get('supportedGenerationMethods', []):
                print(model['name'])
except Exception as e:
    print("Error:", e)