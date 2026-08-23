#!/usr/bin/env python3

"""Export an XMPP account roster and contact vCards to JSON."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from slixmpp import ClientXMPP
from slixmpp.stanza.roster import Roster
from slixmpp.jid import JID
import logging
from typing import NamedTuple, Optional
from slixmpp.plugins.xep_0045.muc import XEP_0045
from collections import defaultdict
import re

from os import chdir
from os.path import dirname, abspath, isfile
import requests

chdir(dirname(abspath(__file__)))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

GG = '@' + os.environ['GOOGLE_COMPONENT_JID']
TAIL_XMPP_DOMAIN = '.' + os.environ['XMPP_DOMAIN']
URL_ROSTER_FIX = os.environ['ROSTER_FIX']

def get_json(url: str):
    r = requests.get(url)
    r.raise_for_status()
    js = r.json()
    if not isinstance(js, dict):
        raise ValueError("Expected a dictionary")
    return js


class MyUser(NamedTuple):
    name: str
    groups: Optional[list[str]] = None

    @classmethod
    def build(cls, obj: dict):
        for k, v in list(obj.items()):
            if k not in cls._fields:
                del obj[k]
        return cls(**obj)
    
    def to_dict(self):
        return {
            k: v
            for k, v
            in self._asdict().items()
            if v not in (None, "", [])
        }


def to_tp(*args):
    return tuple(sorted(set(args)))


def read_json(path: str) -> dict[str, int]:
    if not isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


#OUTPUT_FILE = Path(__file__).with_name("roster-fixed.json")
ITEM_KEYS = to_tp('ask', 'name', 'groups', 'subscription', 'approved')
FIX = {k: MyUser.build(v) for k, v in get_json(URL_ROSTER_FIX).items()}
GRP_ROOMS = {k: to_tp(*v) for k, v in read_json("rooms.json").items()}

OUTPUT_FILE = Path(__file__).parent.parent / "prosody/data/roster-names.json"

class RosterExporter(ClientXMPP):
    def __init__(self, jid: str, password: str) -> None:
        super().__init__(jid, password)
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0199")
        self.register_plugin("xep_0045")
        self.add_event_handler("session_start", self.export)

    async def __export(self, _event: Any) -> dict[str, MyUser]:
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

        contacts: dict[str, MyUser] = {}
        for jid, item in roster_items.items():
            if not isinstance(jid, JID):
                logger.critical(f"jid = {type(jid)}")
                continue
            if not jid.jid.endswith(TAIL_XMPP_DOMAIN):
                continue
            if not isinstance(item, dict):
                logger.critical(f"item = {type(item)}")
                continue
            item_k = to_tp(*item.keys())
            if ITEM_KEYS != to_tp(*item_k):
                logger.warning(f"item {item_k}")

            user = FIX.get(jid.jid, MyUser(
                name=item['name'],
                #groups=to_tp(*item["groups"])
            ))
            group_by_room = user_group.get(jid.jid)

            if jid.jid.endswith(GG) and "Deleted User" == user.name:
                user = user._replace(
                    groups=["🗑", ]
                )
            if group_by_room:
                user = user._replace(
                    groups=to_tp(*group_by_room, *(user.groups or ()))
                )
                if user.name:
                    user = user._replace(
                        name=re.sub(r"\s+<[^<>]+>\s*$", "", user.name)
                    )

            user = user._replace(name=clean_name(user.name))
            contacts[jid.jid] = user
        return contacts

    async def export(self, _event: Any) -> None:
        try:
            data = await self.__export(_event)
            OUTPUT_FILE.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in data.items()},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True
                ),
                encoding="utf-8",
            )
            print(f"Roster exported to {OUTPUT_FILE}")
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


def clean_name(name: str) -> str:
    if name in (None, ""):
        return None
    if re.match(r"^\s*\+[\d\s]+$", name):
        return None
    if name in (name.upper(), name.lower()):
        return name.title()
    return name


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