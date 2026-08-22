#!/usr/bin/env python3

"""Export an XMPP account roster and contact vCards to JSON."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from slixmpp import ClientXMPP
from slixmpp.stanza.roster import Roster, ElementBase
from slixmpp.jid import JID
from slixmpp.plugins.xep_0054.stanza import VCardTemp, Photo
from slixmpp.exceptions import IqError
import mimetypes
import logging
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from typing import NamedTuple, Optional
from slixmpp.plugins.xep_0045.muc import XEP_0045
from collections import defaultdict

from os import chdir
from os.path import dirname, abspath, isfile
import time

chdir(dirname(abspath(__file__)))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

GG = '@' + os.environ['GOOGLE_COMPONENT_JID']


def _eq(a, b):
    if (a, b) == (None, None):
        return True
    if None in (a, b):
        return False
    if isinstance(a, (list, set, tuple)):
        a = to_tp(*a)
    if isinstance(b, (list, set, tuple)):
        b = to_tp(*b)
    if not (type(a) is type(b)):
        return False
    return a == b


class MyUser(NamedTuple):
    name: str
    groups: Optional[list[str]] = None
    avatar: Optional[str] = None

    def get_update_kwargs(self, **kwargs):
        nw = {}
        for k, v in self._asdict().items():
            if not v or k in ("avatar", ):
                continue
            if _eq(v, kwargs.get(k)):
                continue
            nw[k] = v
        return nw

    @classmethod
    def build(cls, obj: dict):
        for k, v in list(obj.items()):
            if k not in cls._fields:
                del obj[k]
        return cls(**obj)


def get_ext(image_type: str, image_data: bytes):
    ext = mimetypes.guess_extension(image_type)
    if ext not in (None, ''):
        return ext
    try:
        img = Image.open(BytesIO(image_data))
    except UnidentifiedImageError:
        return None
    if img.format in ("PNG", "JPEG"):
        return "."+img.format.lower()
    logger.critical(f"ext not found: {img.format}")
    return


def to_tp(*args):
    return tuple(sorted(set(args)))


def read_json(path: str) -> dict[str, int]:
    if not isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


OUTPUT_FILE = Path(__file__).with_name("roster.json")
ITEM_KEYS = to_tp('ask', 'name', 'groups', 'subscription', 'approved')
DIR_AVATAR = Path(__file__).parent / "avatar"
if not DIR_AVATAR.is_dir():
    DIR_AVATAR.mkdir()
FIX = {k: MyUser.build(v) for k, v in read_json("roster_fix.json").items()}
GRP_ROOMS = {k: to_tp(*v) for k, v in read_json("rooms.json").items()}


class RosterExporter(ClientXMPP):
    def __init__(self, jid: str, password: str) -> None:
        super().__init__(jid, password)
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0199")
        self.register_plugin("xep_0045")
        self.add_event_handler("session_start", self.export)

    async def __export(self, _event: Any) -> None:
        user_group = await self.get_groups_by_room()
        roster_iq = await self.get_roster()
        if roster_iq is None:
            logger.critical("roster_iq = None")
            return {}
        roster = roster_iq["roster"]
        if not isinstance(roster, Roster):
            logger.critical(f"roster = {type(roster)}")
            return {}

        roster_items = roster.get_items()

        contacts: dict[str] = {}
        for jid, item in roster_items.items():
            if not isinstance(jid, JID):
                logger.critical(f"jid = {type(jid)}")
                continue
            if not isinstance(item, dict):
                logger.critical(f"item = {type(item)}")
                continue
            item_k = to_tp(*item.keys())
            if ITEM_KEYS != to_tp(*item_k):
                logger.warning(f"item {item_k}")

            name = item['name']
            groups = to_tp(*item["groups"])

            fx = FIX.get(jid.jid)
            group_by_room = user_group.get(jid.jid)

            if jid.jid.endswith(GG) and "Deleted User" == name:
                fx = (fx or MyUser(name=name))._replace(
                    groups=["🗑", ]
                )
            elif group_by_room:
                fx = (fx or MyUser(name=name))._replace(
                    groups=list(group_by_room)
                )
            if fx:
                kwargs = fx.get_update_kwargs(
                    name=name,
                    groups=groups,
                )
                if kwargs:
                    logger.info(f"{jid.jid} = {kwargs}")
                    await self.update_roster(
                        jid,
                        **kwargs
                    )

            ct = {
                "jid": jid.jid,
                "name": name,
                "groups": groups,
            }

            vcard = await self.__get_vcard(jid.jid)
            if vcard:
                for k in to_tp(*set(vcard.keys()).intersection({
                    'FN',
                    'NICKNAME',
                    'EMAIL',
                    'TEL',
                    'URL'
                })):
                    v = vcard[k]
                    if isinstance(v, ElementBase):
                        if k == "EMAIL":
                            v = k['USERID']
                        if k == 'TEL':
                            v = k['NUMBER']
                    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], str):
                        v = v[0]
                    if not v:
                        continue
                    if isinstance(v, str):
                        ct[k] = v
                    else:
                        logger.warning(f"{k} = {v}")

            contacts[jid.jid] = ct

        return tuple(contacts.values())

    async def __get_vcard(self, jid: str) -> VCardTemp | None:
        try:
            vcard = await self.plugin["xep_0054"].get_vcard(jid=jid)
        except IqError:
            return None
        if vcard is None:
            return None
        value = vcard["vcard_temp"]
        if not isinstance(value, VCardTemp):
            logger.critical(f"vcard = {type(value)}")
        self.__save_avatar(jid, value['PHOTO'])
        return value

    def __save_avatar(self, jid: str, photo: Photo):
        if photo is None:
            return
        if isinstance(photo, str) and len(photo.strip()) == 0:
            return
        if not isinstance(photo, Photo):
            logger.critical(f"{jid} photo {type(photo)}")
            return
        image_data = photo['BINVAL']
        if not isinstance(image_data, bytes):
            logger.critical(f"{jid} BINVAL {type(image_data)}")
            return
        image_type = photo['TYPE']
        if not isinstance(image_type, str):
            logger.critical(f"{jid} TYPE {type(image_type)}")
            return
        if (image_type, image_data) == ('', b''):
            return

        ext = get_ext(image_type, image_data)
        if ext is None:
            logger.critical(f"{jid} TYPE = {image_type}")
            return

        filename = DIR_AVATAR / f'{jid}{ext}'
        filename.write_bytes(image_data)

    async def export(self, _event: Any) -> None:
        try:
            data = await self.__export(_event)
            OUTPUT_FILE.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True
                ),
                encoding="utf-8",
            )
            print("DONE")
        finally:
            await self.disconnect(wait=2.0)
            asyncio.get_running_loop().stop()

    async def get_participants(self, room_jid: str):
        plg: XEP_0045 = self.plugin['xep_0045']
        affiliations = ('owner', 'admin', 'member')
        occupants: set[str] = set()
        for affiliation in affiliations:
            iq = await plg.get_users_by_affiliation(
                room_jid,
                affiliation,
            )
            for i in iq:
                occupants.add(i)
        return to_tp(*occupants)

    async def get_groups_by_room(self):
        user_groups: dict[str, set[str]] = defaultdict(set)

        rooms: set[str] = set()
        for ids in GRP_ROOMS.values():
            rooms.update(ids)

        for room_jid in rooms:
            users = await self.get_participants(room_jid)
            for u in users:
                if u == self.boundjid.bare:
                    continue
                for g, rooms in GRP_ROOMS.items():
                    if room_jid in rooms:
                        user_groups[u].add(g)

        return {k: to_tp(*v) for k,v in user_groups.items()}


def main() -> None:
    xmpp = RosterExporter(
        os.environ["XMPP_ADMIN"],
        os.environ["XMPP_ADMIN_PASSWORD"]
    )
    loop = asyncio.get_event_loop()
    xmpp.connect()
    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        loop.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)