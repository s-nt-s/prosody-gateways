#!/usr/bin/env python3

import asyncio
from io import BytesIO
from mimetypes import guess_extension
import os
import sys
from pathlib import Path
from typing import Any
from slixmpp import ClientXMPP
from slixmpp.stanza.roster import Roster
from slixmpp.jid import JID
from slixmpp.plugins.xep_0054 import XEP_0054
from slixmpp.plugins.xep_0054.stanza import Photo
from typing import NamedTuple
import logging
from PIL import Image, UnidentifiedImageError

from os import chdir
from os.path import dirname, abspath


chdir(dirname(abspath(__file__)))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TAIL_XMPP_DOMAIN = '.' + os.environ['XMPP_DOMAIN']
OUTPUT_DIR = Path(__file__).parent / "avatar"
OUTPUT_DIR.mkdir(exist_ok=True)


class Acatar(NamedTuple):
    content: bytes
    extension: str = ".bin"


def get_extension(content_type: str, content: bytes):
    if content_type:
        ext = guess_extension(content_type)
        if ext:
            return ext
    try:
        image_format = Image.open(BytesIO(content)).format
        if image_format:
            return f".{image_format.lower()}"
    except (UnidentifiedImageError, OSError):
        pass


def get_avatar(jid: JID, photo: Photo):
    if not photo:
        return None
    content = photo["BINVAL"]
    if not content:
        return None
    avatar = Acatar(
        content=content
    )
    content_type = photo["TYPE"]
    extension = get_extension(photo["TYPE"], content)
    if not extension:
        logger.warning(
            f"type={content_type or None} extension=None for {jid.bare}"
        )
        return avatar
    return avatar._replace(extension=extension)


class RosterExporter(ClientXMPP):
    def __init__(self, jid: str, password: str) -> None:
        super().__init__(jid, password)
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0054")
        self.register_plugin("xep_0199")
        self.register_plugin("xep_0045")
        self.register_plugin("xep_0054")
        self.add_event_handler("session_start", self.download)

    @property
    def xep_0054(self) -> XEP_0054:
        return self.plugin["xep_0054"]

    async def __download(self, _event: Any):
        roster_iq = await self.get_roster()
        if roster_iq is None:
            logger.critical("roster_iq = None")
            return {}
        roster = roster_iq["roster"]
        if not isinstance(roster, Roster):
            logger.critical(f"roster = {type(roster)}")
            return {}

        roster_items = roster.get_items()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        for jid, item in roster_items.items():
            if not isinstance(jid, JID):
                logger.critical(f"jid = {type(jid)}")
                continue
            if "@" not in jid.jid or not jid.jid.endswith(TAIL_XMPP_DOMAIN):
                continue
            dom = jid.jid.split("@")[-1]
            if dom.startswith("irc."):
                continue
            if not isinstance(item, dict):
                logger.critical(f"item = {type(item)}")
                continue
            try:
                vcard = await self.xep_0054.get_vcard(jid)
                photo = vcard["vcard_temp"]["PHOTO"]
                if not isinstance(photo, Photo):
                    logger.critical(f"vcard_temp.PHOTO = {type(jid)}")
                    continue
                avatar = get_avatar(jid, photo)
                if avatar is None:
                    continue
                output = OUTPUT_DIR / f"{jid.bare}{avatar.extension}"
                output.write_bytes(avatar.content)
            except Exception as e:
                logger.exception(f"[KO] {jid.bare} {e}")

    async def download(self, _event: Any) -> None:
        try:
            await self.__download(_event)
            print(f"Avatars download in {OUTPUT_DIR}")
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
