#!/usr/bin/env python3

import asyncio
import argparse
import os
import logging

from telethon import TelegramClient, functions

os.chdir(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

PAGE_SIZE = 100


async def main(community: str) -> None:
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]

    async with TelegramClient("telegram_lookup", api_id, api_hash) as client:
        chat = await client.get_entity(community)

        print(f"Comunidad: {getattr(chat, 'title', community)}")
        print(f"Chat ID: {chat.id}")
        print()

        topics = []
        seen_ids = set()
        offset_date = None
        offset_id = 0
        offset_topic = 0

        while True:
            result = await client(
                functions.messages.GetForumTopicsRequest(
                    peer=chat,
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=PAGE_SIZE,
                )
            )
            page = [
                topic for topic in result.topics if topic.id not in seen_ids
            ]
            topics.extend(page)
            seen_ids.update(topic.id for topic in page)

            if len(result.topics) < PAGE_SIZE:
                break

            last_topic = result.topics[-1]
            cursor = (last_topic.date, last_topic.top_message, last_topic.id)
            if cursor == (offset_date, offset_id, offset_topic):
                logger.warning(
                    "La API repitió la página; se detiene la paginación."
                )
                break
            offset_date, offset_id, offset_topic = cursor

        print("SUBGRUPOS (temas):")
        print("-" * 60)
        for topic in topics:
            print(f"ID: {topic.id}")
            print(f"Título: {topic.title}")
            print(f"Mensaje raíz: {topic.top_message}")
            print()

        if not topics:
            print(
                "No se encontraron temas. Comprueba que la comunidad sea "
                "un supergrupo con temas activados."
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lista los subgrupos/temas de una comunidad de Telegram."
    )
    parser.add_argument(
        "community",
        help="username, enlace o ID de la comunidad"
    )
    args = parser.parse_args()

    asyncio.run(
        main(args.community)
    )
