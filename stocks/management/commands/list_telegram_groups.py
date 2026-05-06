import asyncio
from django.core.management.base import BaseCommand
from decouple import config
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat


class Command(BaseCommand):
    help = '가입된 텔레그램 그룹/채널 목록 조회'

    def handle(self, *args, **options):
        api_id = config('TELEGRAM_API_ID')
        api_hash = config('TELEGRAM_API_HASH')

        asyncio.run(self.list_groups(api_id, api_hash))

    async def list_groups(self, api_id, api_hash):
        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            dialogs = await client.get_dialogs()

            self.stdout.write(self.style.SUCCESS('\n=== 그룹/채널 목록 ===\n'))
            for dialog in dialogs:
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    entity_type = '채널' if getattr(entity, 'broadcast', False) else '그룹'
                    username = getattr(entity, 'username', None)
                    display = f'@{username}' if username else f'ID: {entity.id}'
                    self.stdout.write(f'[{entity_type}] {dialog.name}  →  {display}')
