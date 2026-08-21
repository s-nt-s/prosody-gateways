#!/usr/bin/env python3

"""Export an XMPP account roster and contact vCards to JSON."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from slixmpp import ClientXMPP
from slixmpp.stanza.roster import Roster
from slixmpp.jid import JID
from slixmpp.plugins.xep_0054.stanza import VCardTemp
from slixmpp.exceptions import IqError
import logging

logger = logging.getLogger(__name__)

def to_tp(*args):
    return tuple(sorted(set(args)))

OUTPUT_FILE = Path(__file__).with_name("roster.json")
ITEM_KEYS = to_tp('ask', 'name', 'groups', 'subscription', 'approved')


class RosterExporter(ClientXMPP):
    def __init__(self, jid: str, password: str) -> None:
        super().__init__(jid, password)
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0199")
        self.add_event_handler("session_start", self.export)


    async def __export(self, _event: Any) -> None:
        roster_iq = await self.get_roster()
        if roster_iq is None:
            logger.critical(f"roster_iq = None")
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

            #vcard = await self.__get_vcard(jid.jid)
            #if vcard:
            #    print(vcard)

            contacts[jid.jid] = {
                "jid": jid.jid,
                "name": item['name'],
                "groups": to_tp(*item["groups"]),
            }

        return contacts

    async def __get_vcard(self, jid: str):
        try:
            vcard = await self.plugin["xep_0054"].get_vcard(jid=jid)
        except IqError:
            return None
        if vcard is None:
            return None
        value = vcard["vcard_temp"]
        if isinstance(value, VCardTemp):
            return value
        logger.critical(f"vcard = {type(value)}")


    async def export(self, _event: Any) -> None:
        try:
            data =  await self.__export(_event)
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