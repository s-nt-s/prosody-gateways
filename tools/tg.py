#!/usr/bin/env python3

import asyncio
import json
import os
import sys

from telethon import TelegramClient
from telethon.tl.types import User
from telethon import TelegramClient, functions
from telethon.tl.types import InputPhoneContact
from telethon.tl.types.contacts import ImportedContacts
from telethon.tl.custom.dialog import Dialog
from telethon.tl.patched import Message
from telethon.tl.types.contacts import ResolvedPeer
from telethon.errors.rpcerrorlist import PhoneNotOccupiedError
import logging

from os import chdir
from os.path import dirname, abspath, isfile

chdir(dirname(abspath(__file__)))

logger = logging.getLogger(__name__)


class MyClient(TelegramClient):
    async def get_user(self, phone: str):
        try:
            r = await self(
                functions.contacts.ResolvePhoneRequest(
                    phone=phone
                )
            )
        except PhoneNotOccupiedError:
            return None
        if not isinstance(r, ResolvedPeer):
            return None
        users: list[User] = []
        for u in r.users:
            if isinstance(u, User):
                users.append(u)
        size = len(users)
        if size == 0:
            return None
        if size > 1:
            logger.warning(f"{phone} has {size} users")
        return users[0]


    async def iter_users(self):
        async for dialog in self.iter_dialogs():
            if not isinstance(dialog, Dialog):
                continue
            entity = dialog.entity

            if isinstance(entity, User):
                yield entity
                continue

            try:
                async for user in self.iter_participants(entity):
                    yield user
                continue
            except:
                pass

            async for message in self.iter_messages(
                entity,
                limit=MESSAGES_PER_DIALOG,
            ):
                if isinstance(entity, Message):
                    if isinstance(message.sender, User):
                        yield message.sender


def read_json(path: str) -> dict[str, int]:
    if not isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: str, data: dict):
    data = dict(sorted(data.items(), key=lambda x: (x[1] is None, x)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


OUTPUT_FILE = "tg.json"
BATCH_SIZE = 100
MESSAGES_PER_DIALOG = 100000
REQUEST_DELAY = 3.1

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
DATA: dict[str, int] = read_json(OUTPUT_FILE)


def parse_num(t: str):
    if len(t) == 9 and not t.startswith("+"):
        return "+34"+t
    if t[0]!='+':
        raise ValueError(t)
    return t


PHONES = tuple(sorted(
    set(map(parse_num, sys.argv[1:])).difference(DATA.keys())
))


def add_kv(p:str, i: int):
    p = parse_num(p)
    if i is not None and DATA.get(p) != i:
        print(p, i)
    DATA[p] = i
    if len(DATA) % 100 == 0:
        write_json(OUTPUT_FILE, DATA)


def add_user(user):
    if isinstance(user, User) and user.phone:
        add_kv('+'+user.phone, user.id)


async def do_lookup(client: MyClient, phones: tuple[str]):
    results: dict[str, int] = {}
    contacts = [
        InputPhoneContact(
            client_id=i,
            phone=phone,
            first_name=f"lookup_{i}",
            last_name="",
        )
        for i, phone in enumerate(phones)
    ]

    response: ImportedContacts = await client(
        functions.contacts.ImportContactsRequest(
            contacts=contacts
        )
    )

    for user in response.users:
        add_user(user)

    return results


async def do_import(client: MyClient, phones: tuple[str]):
    for offset in range(0, phones, BATCH_SIZE):
        if offset > 0:
            await asyncio.sleep(1)
        DATA.update(
            await do_lookup(
                client,
                phones[offset:offset + BATCH_SIZE]
            )
        )


async def do_search(client: MyClient):
    async for user in client.iter_users():
        add_user(user)


async def do_main():
    client = MyClient(
        "telegram_lookup",
        API_ID,
        API_HASH,
    )
    await client.start()

    try:
        #await do_search(client)
        await resolve_lookup(
            client,
            tuple(sorted(set(PHONES).difference(DATA.keys())))
        )
        #await do_import(
        #    client,
        #    tuple(sorted(set(PHONES).difference(DATA.keys())))
        #)
    finally:
        await client.disconnect()

    write_json(OUTPUT_FILE, DATA)


async def resolve_lookup(client: MyClient, phones: tuple[str, ...]):
    for p in phones:
        await asyncio.sleep(REQUEST_DELAY)
        user = await client.get_user(p)
        if user is None:
            add_kv(p, None)
        else:
            add_kv(p, user.id)


if __name__ == "__main__":
    if False:
        PHONES = set()
        for k, v in list(DATA.items()):
            if v is None:
                del DATA[k]
                PHONES.add(k)
        PHONES = tuple(sorted(PHONES))
    asyncio.run(do_main())