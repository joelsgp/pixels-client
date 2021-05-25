#!/usr/bin/env python

import json
import time
from pathlib import Path

import requests


CONFIG_FILE_PATH = Path('config.json')
SET_URL = 'https://pixels.pythondiscord.com/set_pixel'


def ratelimit(headers):
    requests_remaining = int(headers['requests-remaining'])
    print(f'{requests_remaining} requests remaining')
    if not requests_remaining:
        requests_reset = int(headers['requests-reset'])
        print(f'sleeping for {requests_reset} seconds')
        time.sleep(requests_reset)


def set_pixel(x: int, y: int, rgb: str, headers:dict):
    payload = {
        'x': x,
        'y': y,
        'rgb': rgb,
    }
    r = requests.post(
        SET_URL,
        json=payload,
        headers=headers
    )

    ratelimit(r.headers)


def main():
    with open(CONFIG_FILE_PATH) as config_file:
        config = json.load(config_file)

    bearer_token = f"Bearer {config['token']}"
    headers = {
        "Authorization": bearer_token
    }


if __name__ == '__main__':
    main()
