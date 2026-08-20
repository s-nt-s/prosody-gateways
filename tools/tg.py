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

from os import chdir
from os.path import dirname, abspath, isfile

chdir(dirname(abspath(__file__)))

def read_json(path: str) -> dict[str, int]:
    if not isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: str, data: dict):
    data = dict(sorted(data.items()))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


OUTPUT_FILE = "tg.json"
BATCH_SIZE = 100
MESSAGES_PER_DIALOG = 10000
REQUEST_DELAY = 3.1

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
DATA: dict[str, int] = read_json(OUTPUT_FILE)

PHONES = tuple(sorted(set(sys.argv[1:]).difference(DATA.keys())))


def add_kv(p:str, i: int):
    p = f"+{p}"
    print(p, i)
    DATA[p] = i


def add_user(user):
    if isinstance(user, User) and user.phone:
        add_kv(user.phone, user.id)


async def do_lookup(client: TelegramClient, phones: tuple[str]):
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
        if user.phone:
            ph = f"+{user.phone}"
            results[ph] = user.id

    return results


async def do_import(client: TelegramClient, phones: tuple[str]):
    for offset in range(0, phones, BATCH_SIZE):
        batch = phones[offset:offset + BATCH_SIZE]
        DATA.update(
            await do_lookup(client, batch)
        )

        # Evita encadenar inmediatamente todas las peticiones.
        if offset + BATCH_SIZE < len(phones):
            await asyncio.sleep(1)


async def do_search(client: TelegramClient):
    async for dialog in client.iter_dialogs():
        if not isinstance(dialog, Dialog):
            continue
        entity = dialog.entity

        if isinstance(entity, User) and entity.phone:
            add_user(entity)
            continue

        try:
            async for user in client.iter_participants(entity):
                add_user(user)
            continue
        except:
            pass

        async for message in client.iter_messages(
            entity,
            limit=MESSAGES_PER_DIALOG,
        ):
            if not isinstance(entity, Message):
                continue
            add_user(message.sender)


async def do_main():
    client = TelegramClient(
        "telegram_lookup",
        API_ID,
        API_HASH,
    )
    await client.start()

    try:
        await do_search(client)
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


async def resolve_lookup(client: TelegramClient, phones: tuple[str, ...]):
    for p in phones:
        await asyncio.sleep(REQUEST_DELAY)
        try:
            response = await client(
                functions.contacts.ResolvePhoneRequest(
                    phone=p
                )
            )
        except PhoneNotOccupiedError:
            continue
        if not isinstance(response, ResolvedPeer):
            continue

        for user in response.users:
            add_user(user)


if __name__ == "__main__":
    asyncio.run(do_main())