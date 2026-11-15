#!/usr/bin/env python3

"""Export Telegram group members as a multi-contact vCard 3.0 file."""

import argparse
import asyncio
import base64
import logging
import os
import re
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger(__name__)
XMPP_DOMAIN = os.environ['TELEGRAM_COMPONENT_JID']
SESSION = "telegram_lookup"


def escape_vcard(value: str) -> str:
    """Escape a text value according to vCard 3.0."""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold_line(line: str, max_octets: int = 75) -> str:
    """Fold a vCard content line without splitting UTF-8 characters."""
    folded: list[str] = []
    current = ""
    current_size = 0
    for char in line:
        char_size = len(char.encode("utf-8"))
        if current_size + char_size > max_octets:
            folded.append(current)
            current = " "
            current_size = 1
        current += char
        current_size += char_size
    folded.append(current)
    return "\r\n".join(folded)


def make_vcard(user: User, avatar: Optional[bytes]) -> str:
    first_name = (user.first_name or "").strip()
    last_name = (user.last_name or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    phone = f"+{user.phone}"
    jid = f"{user.id}@{XMPP_DOMAIN}"

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{escape_vcard(full_name)}",
        "N:{};{};;;".format(escape_vcard(last_name), escape_vcard(first_name)),
        f"TEL;TYPE=CELL:{escape_vcard(phone)}",
        f"JABBERID:{jid}",
    ]
    if avatar:
        encoded_avatar = base64.b64encode(avatar).decode("ascii")
        lines.append(f"PHOTO;ENCODING=b;TYPE=JPEG:{encoded_avatar}")
    lines.append("END:VCARD")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


def output_path(group_name: str, requested_path: Optional[str]) -> Path:
    if requested_path:
        return Path(requested_path).expanduser()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", group_name).strip("-.")
    return Path(__file__).parent / f"{slug or 'telegram-group'}-contacts.vcf"


async def find_group(client: TelegramClient, identifier: str):
    """Resolve a group by its exact dialog title, username, link, or ID."""
    matches = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        title = getattr(entity, "title", None)
        if isinstance(title, str) and title.casefold() == identifier.casefold():
            matches.append(entity)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Hay varios grupos con el nombre {identifier!r}; usa su username, enlace o ID."
        )

    try:
        return await client.get_entity(identifier)
    except Exception as error:
        raise ValueError(
            f"No se encontró el grupo {identifier!r} entre tus diálogos "
            "ni se pudo resolver como username, enlace o ID."
        ) from error


async def export_groups(client: TelegramClient, groups, destination: Path) -> int:
    cards: list[str] = []
    seen_ids: set[int] = set()

    for group in groups:
        async for user in client.iter_participants(group):
            if not isinstance(user, User) or user.id in seen_ids:
                continue
            seen_ids.add(user.id)

            name = " ".join(
                part.strip()
                for part in (user.first_name, user.last_name)
                if isinstance(part, str) and part.strip()
            )
            if not name or not user.phone:
                continue

            try:
                avatar = await client.download_profile_photo(user, file=bytes)
            except Exception:
                logger.warning(
                    "No se pudo descargar el avatar del usuario %s", user.id
                )
                avatar = None

            cards.append(make_vcard(user, avatar))

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cards:
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as output_file:
        output_file.write("".join(cards))
    return len(cards)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un archivo vCard con los miembros de un grupo de Telegram "
            "que tienen nombre y teléfono."
        )
    )
    parser.add_argument(
        "group",
        nargs="*",
        help=(
            "uno o varios grupos: título exacto, username, enlace o ID; "
            "si se omite, exporta todos los grupos de tus diálogos"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "ruta del archivo .vcf para grupos indicados; si no se indican "
            "grupos, carpeta donde guardar un .vcf por grupo"
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    client = TelegramClient(SESSION, api_id, api_hash)
    await client.start()
    try:
        if args.group:
            groups = [
                await find_group(client, identifier)
                for identifier in args.group
            ]
            group_names = [
                getattr(group, "title", identifier)
                for group, identifier in zip(groups, args.group)
            ]
            destination = output_path("-".join(group_names), args.output)
            count = await export_groups(client, groups, destination)
            if count:
                print(f"vCard generado: {destination} ({count} contactos)")
            else:
                print("No hay contactos para exportar; no se creó el archivo.")
        else:
            groups = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                is_group = isinstance(entity, Chat) or (
                    isinstance(entity, Channel)
                    and (entity.megagroup or entity.gigagroup)
                )
                if is_group and getattr(entity, "title", None):
                    groups.append(entity)

            output_directory = (
                Path(args.output).expanduser()
                if args.output
                else Path(__file__).parent
            )
            used_filenames: set[str] = set()
            for group in groups:
                group_title = group.title
                destination = output_path(group_title, None)
                filename = destination.name
                if filename in used_filenames:
                    filename = (
                        f"{destination.stem}-{group.id}{destination.suffix}"
                    )
                used_filenames.add(filename)
                destination = output_directory / filename
                count = await export_groups(client, [group], destination)
                if count:
                    print(f"vCard generado: {destination} ({count} contactos)")
                else:
                    print(
                        f"{group_title}: no hay contactos para exportar; "
                        "no se creó el archivo."
                    )

            if not groups:
                print("No se encontraron grupos en tus diálogos de Telegram.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
