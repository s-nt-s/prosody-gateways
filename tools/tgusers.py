#!/usr/bin/env python3

import asyncio
import json
import sys
from pathlib import Path
import re

from tg import MyClient, parse_phone_or_id, uq, User, safe_read_dict

import logging

logger = logging.getLogger(__name__)



def read_json(path: str) -> dict[str, int]:
    data = safe_read_dict(path)
    tmp = 0
    while True:
        tmp = tmp + 1
        aux = safe_read_dict(f"{path}.{tmp}")
        if not aux:
            break
        for k, v in aux.items():
            if v is not None and data.get(k) is None:
                data[k] = v
    write_json(path, data)
    return data


def write_json(path: str, data: dict):
    data = dict(sorted(data.items(), key=lambda x: (x[1] is None, x)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


OUTPUT_FILE = "tg.json"

DATA: dict[str, int] = read_json(OUTPUT_FILE)
PHONES: tuple[str, ...] = uq(*map(parse_phone_or_id, sys.argv[1:]))


def get_nums():
    roster = Path(__file__).parent.parent / "prosody/data/roster-names.json"
    if not roster.is_file():
        return {}
    with open(roster, "r", encoding="utf-8") as f:
        data = json.load(f)
    nums: set[str] = set()
    for k in data.keys():
        if re.search(r"^\+\d+@.*$", k):
            k = k.split("@")[0]
            if k not in DATA:
                nums.add(k)
    return tuple(sorted(nums))


def get_phones():
    return tuple(p for p in PHONES if p not in DATA)


def add_kv(p: str, i: int):
    if i is not None and DATA.get(p) != i:
        print(p, i)
    DATA[p] = i
    if len(DATA) % 100 == 0:
        write_json(OUTPUT_FILE, DATA)


def add_user(user):
    if isinstance(user, User) and user.phone:
        add_kv('+'+user.phone, user.id)


async def do_main():
    client = MyClient.get()
    async with client:
        #async for u in client.iter_users():
        #    add_user(u)
        async for u in client.get_users(*get_phones()):
            add_user(u)
        async for u in client.iter_import(*get_phones()):
            add_user(u)
    for p in get_phones():
        if DATA.get(p) is None:
            DATA[p] = None
    write_json(OUTPUT_FILE, DATA)


if __name__ == "__main__":
    if len(PHONES) == 0:
        #PHONES = uq(*get_nums(), *(k for k, v in DATA.items() if v is None))
        #DATA = {k: v for k, v in DATA.items() if v is not None}
        PHONES = uq(*get_nums())
        print(*PHONES)
    asyncio.run(do_main())
