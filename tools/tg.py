import asyncio
import os
from collections.abc import AsyncIterator
from typing import TypeVar

from telethon.tl.types import Channel, Chat, User, UserFull
from telethon import TelegramClient, functions
from telethon.tl.types import InputPhoneContact
from telethon.tl.types.contacts import ImportedContacts
from telethon.tl.custom.dialog import Dialog
from telethon.tl.patched import Message
from telethon.tl.types.contacts import ResolvedPeer
from telethon.errors.rpcerrorlist import PhoneNotOccupiedError, FloodWaitError, ChatAdminRequiredError

from typing import NamedTuple
from io import BytesIO
import logging
from PIL import Image, UnidentifiedImageError

from os.path import isfile
import json


logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MESSAGES_PER_DIALOG = 100000
REQUEST_DELAY = 1
TELEGRAM_SESSION = "telegram_lookup"
EntityT = TypeVar("EntityT")


def safe_read_dict(path: str):
    if not isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
        if isinstance(obj, dict):
            return obj


class Img(NamedTuple):
    image_type: str
    content: bytes


def uq(*args: int | str):
    return sorted(set([
        x for x in args if x is not None
    ]), key=lambda x: (
        isinstance(x, str),
        x if isinstance(x, int) else 0,
        x if isinstance(x, str) else '',
    ))


def parse_phone_or_id(t: str | int):
    if t is None:
        return None
    if isinstance(t, int):
        return t
    if len(t) == 9 and not t.startswith("+"):
        return "+34"+t
    if t[0] != '+':
        return '+'+t
    return t


class MyClient(TelegramClient):

    async def __enter__(self):
        await self.start()
        return self

    async def __exit__(self, exc_type, exc_value, traceback):
        await self.disconnect()

    @classmethod
    def get(cls):
        client = cls(
            TELEGRAM_SESSION,
            int(os.environ["TG_API_ID"]),
            os.environ["TG_API_HASH"]
        )
        return client

    async def get_my_id(self) -> int:
        """Return the authenticated Telegram account's user ID."""
        user = await self.get_me()
        if not isinstance(user, User):
            raise RuntimeError("No se pudo obtener el usuario autenticado")
        return user.id

    async def get_user(self, phone_or_id: str | int):
        phone_or_id = parse_phone_or_id(phone_or_id)
        if isinstance(phone_or_id, int):
            try:
                u = await self.get_entity(phone_or_id)
            except ValueError:
                return None
            if not isinstance(u, User):
                return None
            return u
        try:
            r = await self(
                functions.contacts.ResolvePhoneRequest(
                    phone=phone_or_id
                )
            )
        except (PhoneNotOccupiedError, FloodWaitError):
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
            logger.warning(f"{phone_or_id} has {size} users")
        return users[0]

    async def get_users(self, *phone_or_id: str | int):
        phone_or_id = uq(*map(parse_phone_or_id, phone_or_id))
        done: set[int | str] = set()
        for pid in phone_or_id:
            if pid in done:
                continue
            await asyncio.sleep(REQUEST_DELAY)
            user = await self.get_user(pid)
            if user is None:
                continue
            if user.id not in done and user.phone not in done:
                yield user
                done.add(user.id)
                if user.phone is not None:
                    done.add('+'+user.phone)
            done.add(pid)

    async def iter_entities(
        self, *cls: type[EntityT]
    ) -> AsyncIterator[EntityT]:
        async for dialog in self.iter_dialogs():
            if not isinstance(dialog, Dialog):
                continue
            entity = dialog.entity

            if isinstance(entity, cls):
                yield entity

    @property
    def full_user_cache(self) -> dict[int, UserFull]:
        cache = getattr(self, '__full_user_cache', None)
        if cache is not None:
            return cache
        cache = {}
        setattr(self, '__full_user_cache', cache)
        return cache

    async def get_full_user(
        self,
        user: User,
    ) -> UserFull | None:
        if user.id not in self.full_user_cache:
            try:
                r = await self(functions.users.GetFullUserRequest(user))
                self.full_user_cache[user.id] = r.full_user
            except Exception:
                logger.info("No se pudo obtener el perfil completo de %s", user.id)
                self.full_user_cache[user.id] = None
        return self.full_user_cache[user.id]

    async def __iter_users_of_group(self, e: Chat | Channel):
        #async for message in self.iter_messages(
        #    e,
        #    limit=MESSAGES_PER_DIALOG,
        #):
        #    if isinstance(message, Message):
        #        if isinstance(message.sender, User):
        #            yield message.sender
        try:
            async for user in self.iter_participants(e):
                if isinstance(user, User):
                    yield user
        except ChatAdminRequiredError:
            pass

    async def get_avatar(self, u: User):
        img = await self.download_profile_photo(u, file=bytes)
        if img is None:
            return None
        try:
            with Image.open(BytesIO(img)) as image:
                return Img(
                    image_type=image.format,
                    content=img
                )
        except UnidentifiedImageError:
            logger.critical("No se reconoce el avatar de Telegram %s %s", u.id, u.photo)
        return None

    async def iter_users_of_group(self, e: Chat | Channel):
        done: set[int] = set()
        async for u in self.__iter_users_of_group(e):
            if u.id in done:
                continue
            done.add(u.id)
            yield u

    async def __iter_users(self):
        async for e in self.iter_entities(User, Chat, Channel):
            if isinstance(e, User):
                yield e
                continue
            async for u in self.__iter_users_of_group(e):
                yield u

    async def iter_users(self):
        done: set[int] = set()
        async for e in self.__iter_users():
            if e.id in done:
                continue
            done.add(e.id)
            yield e

    async def iter_groups(self):
        async for e in self.iter_entities(Chat, Channel):
            if isinstance(e, Channel) and not (e.megagroup or e.gigagroup):
                continue
            yield e

    async def iter_import(self, *phones: str):
        phones = uq(*map(parse_phone_or_id, phones))
        for offset in range(0, len(phones), BATCH_SIZE):
            if offset > 0:
                await asyncio.sleep(1)
            chunk = phones[offset:offset + BATCH_SIZE]
            contacts = [
                InputPhoneContact(
                    client_id=i,
                    phone=p,
                    first_name=f"lookup_{i}",
                    last_name="",
                )
                for i, p in enumerate(chunk)
            ]
            response: ImportedContacts = await self(
                functions.contacts.ImportContactsRequest(
                    contacts=contacts
                )
            )
            for user in response.users:
                if isinstance(user, User):
                    yield user


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def main():
        client = MyClient.get()
        async with client:
            async for u in client.iter_users():
                print(u.phone, u.first_name)

    asyncio.run(main())
