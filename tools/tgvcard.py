#!/usr/bin/env python3

import asyncio
from datetime import date

from tg import MyClient, User, Img, UserFull, safe_read_dict

import logging
import vobject
import re
from os import makedirs
from collections import defaultdict
from pathlib import Path
import json


logger = logging.getLogger(__name__)

OUT = "/tmp/v"
makedirs(OUT, exist_ok=True)
ALIAS = safe_read_dict("tg_alias.json")


def get_roster() -> dict[str, str]:
    roster = Path(__file__).parent.parent / "prosody/data/roster-names.json"
    if not roster.is_file():
        return {}
    with open(roster, "r", encoding="utf-8") as f:
        data = json.load(f)
    roster: dict[str, str] = dict()
    for k, v in data.items():
        if re.search(r"^\+\d+@.*$", k) and isinstance(v, dict):
            k = k.split("@")[0]
            g = v.get("groups")
            if not isinstance(g, list):
                continue
            g = [x for x in g if x not in ("WhatsApp", )]
            if len(g) > 0:
                roster[k] = g[0]
    return roster


def simplify(s: str):
    s = s.lower()
    for k, v in {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
    }.items():
        s = s.replace(k, v)
    s = re.sub(r"[\s\-:…🏆]+", " ", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def user_to_vcard(
    u: User,
    avatar: Img | None = None,
    full: UserFull | None = None,
):
    card = vobject.vCard()

    first_name = (u.first_name or "").strip()
    last_name = (u.last_name or "").strip()
    username = (u.username or "").strip().lstrip("@")
    phone = (u.phone or "").strip()
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"

    full_name = " ".join(part for part in (first_name, last_name) if part)
    if not full_name:
        full_name = username or phone or f"Telegram user {u.id}"

    card.add("version").value = "3.0"
    card.add("fn").value = full_name
    card.add("n").value = vobject.vcard.Name(
        family=last_name,
        given=first_name,
        additional="",
        prefix="",
        suffix="",
    )
    card.add("uid").value = f"tg://user?id={u.id}"

    if username:
        card.add("nickname").value = username

    if phone:
        telephone = card.add("tel")
        telephone.value = phone
        telephone.params["TYPE"] = ["CELL"]

    usernames: list[str] = []
    if username:
        usernames.append(username)
    for alias in u.usernames or []:
        alias_name = alias.username.strip().lstrip("@")
        if alias.active and alias_name and alias_name not in usernames:
            usernames.append(alias_name)
    for alias_name in usernames:
        card.add("url").value = f"https://t.me/{alias_name}"

    if avatar:
        photo = card.add("photo")
        photo.value = avatar.content
        photo.encoding_param = "b"
        photo.params["TYPE"] = [avatar.image_type.upper()]

    notes: list[str] = []
    if full:
        birthday = full.birthday
        if full.birthday and birthday.year:
            dt = date(birthday.year, birthday.month, birthday.day)
            card.add("bday").value = f"{dt:%Y-%m-%d}"

        if full.about:
            notes.append(full.about)
        if full.note and full.note.text:
            notes.append(full.note.text)
        if full.bot_info and full.bot_info.description:
            notes.append(full.bot_info.description)

        if full.business_intro:
            if full.business_intro.title:
                card.add("title").value = full.business_intro.title
            if full.business_intro.description:
                notes.append(full.business_intro.description)

        if full.business_location and full.business_location.address:
            address = card.add("adr")
            address.value = vobject.vcard.Address(
                box="",
                extended="",
                street=full.business_location.address,
                city="",
                region="",
                code="",
                country="",
            )
            address.params["TYPE"] = ["WORK"]
        if full.business_location and full.business_location.geo_point:
            latitude = full.business_location.geo_point.lat
            longitude = full.business_location.geo_point.lon
            if latitude is not None and longitude is not None:
                card.add("geo").value = f"{latitude};{longitude}"

    if notes:
        card.add("note").value = "\n\n".join(notes)

    categories = ["Telegram"]
    if u.bot:
        categories.append("Bot")
    if u.premium:
        categories.append("Premium")
    if u.verified:
        categories.append("Verified")
    if u.support:
        categories.append("Support")
    if u.scam:
        categories.append("Scam")
    if u.fake:
        categories.append("Fake")
    card.add("categories").value = categories

    return card




async def do_main():
    phones: set[int] = set()
    done: set[int] = set()
    client = MyClient.get()
    ROSTER = get_roster()
    file_vcards: dict[str, set[str]] = defaultdict(set)
    async with client:
        my_id = await client.get_my_id()

        async def get_vcard(iu: User):
            if iu.id == my_id or iu.phone is None:
                return None
            return user_to_vcard(
                iu,
                await client.get_avatar(iu),
                await client.get_full_user(iu)
            )

        print("YO:", my_id)
        async for g in client.iter_groups():
            name = simplify(g.title)
            print(name)
            name = ALIAS.get(name, name)
            file = f"{OUT}/{name}.vcf"
            async for u in client.iter_users_of_group(g):
                done.add(u.id)
                if u.phone:
                    phones.add('+'+u.phone)
                card = await get_vcard(u)
                if card is not None:
                    file_vcards[file].add(card.serialize())
        ids = tuple(
            v for k, v in safe_read_dict("tg.json").items()
            if isinstance(v, int) and v not in done and
            k not in phones
        )
        async for u in client.get_users(*ids):
            card = await get_vcard(u)
            if card is not None:
                name = simplify(ROSTER.get(f"+{u.phone}", "otros"))
                file_vcards[f"{OUT}/{name}.vcf"].add(card.serialize())
        for file, cards in file_vcards.items():
            print(file)
            with open(file, "w", encoding="utf-8") as f:
                for c in sorted(cards):
                    f.write(c)


if __name__ == "__main__":
    asyncio.run(do_main())
