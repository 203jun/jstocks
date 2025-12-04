import asyncio
from collections import defaultdict
from django.core.management.base import BaseCommand
from decouple import config
from telethon import TelegramClient


class Command(BaseCommand):
    help = '텔레그램 채널에서 키워드 검색'

    def add_arguments(self, parser):
        parser.add_argument('--channel', '-c', required=True, help='채널명 (예: @darthacking)')
        parser.add_argument('--keyword', '-k', required=True, help='검색 키워드')
        parser.add_argument('--limit', '-l', type=int, default=50, help='검색 결과 수 (기본: 50)')

    def handle(self, *args, **options):
        channel = options['channel']
        keyword = options['keyword']
        limit = options['limit']

        api_id = config('TELEGRAM_API_ID')
        api_hash = config('TELEGRAM_API_HASH')

        self.stdout.write(f'채널: {channel}')
        self.stdout.write(f'검색어: {keyword}')
        self.stdout.write(f'검색 수: {limit}개')
        self.stdout.write('-' * 50)

        asyncio.run(self.search(api_id, api_hash, channel, keyword, limit))

    async def search(self, api_id, api_hash, channel, keyword, limit):
        async with TelegramClient('telegram_session', api_id, api_hash) as client:
            entity = await client.get_entity(channel)

            messages = await client.get_messages(
                entity,
                search=keyword,
                limit=limit
            )

            if not messages:
                self.stdout.write(self.style.WARNING('검색 결과 없음'))
                return

            # 날짜별 그룹핑
            by_date = defaultdict(list)
            for msg in messages:
                if msg.text:
                    date_str = msg.date.strftime('%Y-%m-%d')
                    by_date[date_str].append({
                        'time': msg.date.strftime('%H:%M'),
                        'text': msg.text
                    })

            # 날짜별 출력 (최신순)
            for date in sorted(by_date.keys(), reverse=True):
                self.stdout.write(self.style.SUCCESS(f'\n=== {date} ({len(by_date[date])}건) ==='))
                for item in by_date[date]:
                    text_preview = item['text'][:200].replace('\n', ' ')
                    self.stdout.write(f"[{item['time']}] {text_preview}")
                    if len(item['text']) > 200:
                        self.stdout.write('...')
                    self.stdout.write('')

            self.stdout.write(self.style.SUCCESS(f'\n총 {len(messages)}건 검색됨'))
