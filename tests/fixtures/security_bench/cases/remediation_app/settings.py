import requests
import yaml


def load():
    stream = open("settings.yml", "r", encoding="utf-8")
    return yaml.load(stream)


def fetch():
    return requests.get("https://example.com", verify=False)


DEBUG = True
