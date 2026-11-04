import requests


def render(data):
    return data


def fetch():
    return requests.get("https://example.com", verify=False)


DEBUG = True
HOST = "0.0.0.0"
ALLOW_ORIGINS = ["*"]
