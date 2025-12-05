# -*- coding: utf-8 -*-
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from stocks.models import MarketTrend
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = 'Market investor trading trend (Naver Finance)'

    # Market codes
    MARKET_CODES = {
        'KOSPI': '01',
        'KOSDAQ': '02',
        'FUTURES': '03',
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--market',
            type=str,
            default='all',
            help='Market: KOSPI, KOSDAQ, FUTURES, all (default: all)'
        )
        parser.add_argument(
            '--mode',
            type=str,
            default='day',
            choices=['all', 'day'],
            help='all: 6 pages (60 days), day: 1 page (10 days) (default: day)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'save_market_trend')

        market = options['market'].upper()
        mode = options['mode']
        max_page = 6 if mode == 'all' else 1

        if market == 'ALL':
            markets = list(self.MARKET_CODES.keys())
        elif market in self.MARKET_CODES:
            markets = [market]
        else:
            self.log.error(f'Unsupported market: {market}')
            self.log.info(f'Supported: {", ".join(self.MARKET_CODES.keys())}')
            return

        self.log.info(f'Market trend collection started (mode={mode}, max_page={max_page})')

        for market_name in markets:
            self.process_market(market_name, max_page)

        self.log.separator()
        self.log.info('Collection completed', success=True)

    def process_market(self, market_name, max_page):
        """Collect data for each market"""
        self.log.separator()
        self.log.info(f'[{market_name}] Collection started')

        sosok = self.MARKET_CODES[market_name]
        all_data = []

        # Get today's date for bizdate parameter
        bizdate = datetime.now().strftime('%Y%m%d')

        for page in range(1, max_page + 1):
            # Use iframe URL with bizdate
            url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate}&sosok={sosok}&page={page}'
            self.log.debug(f'  Page {page} fetching... {url}')

            data = self.fetch_page(url)
            if data:
                all_data.extend(data)
                self.log.debug(f'  -> {len(data)} rows collected')
            else:
                self.log.debug(f'  -> No data')
                break

        # Save to DB
        if all_data:
            self.save_to_db(market_name, all_data)
        else:
            self.log.info(f'[{market_name}] No data to save')

    def fetch_page(self, url):
        """Extract table data from page"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            response.encoding = 'euc-kr'

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find table with date header
            table = soup.select_one('table.type_1')
            if not table:
                self.log.debug(f'  Table not found')
                return []

            rows = []
            # Try tbody first, then table directly
            tbody = table.select_one('tbody')
            if tbody:
                all_trs = tbody.select('tr')
            else:
                all_trs = table.select('tr')
            self.log.debug(f'  Found {len(all_trs)} rows')

            for tr in all_trs:
                tds = tr.select('td')
                if len(tds) < 4:
                    continue

                date_text = tds[0].get_text(strip=True)
                if not date_text or not date_text[0].isdigit():
                    continue

                # Flexible column parsing
                row = {
                    'date': date_text,
                    'individual': self.parse_number(tds[1].get_text(strip=True)) if len(tds) > 1 else 0,
                    'foreign': self.parse_number(tds[2].get_text(strip=True)) if len(tds) > 2 else 0,
                    'institution': self.parse_number(tds[3].get_text(strip=True)) if len(tds) > 3 else 0,
                    'financial_investment': self.parse_number(tds[4].get_text(strip=True)) if len(tds) > 4 else 0,
                    'insurance': self.parse_number(tds[5].get_text(strip=True)) if len(tds) > 5 else 0,
                    'trust': self.parse_number(tds[6].get_text(strip=True)) if len(tds) > 6 else 0,
                    'bank': self.parse_number(tds[7].get_text(strip=True)) if len(tds) > 7 else 0,
                    'other_financial': self.parse_number(tds[8].get_text(strip=True)) if len(tds) > 8 else 0,
                    'pension_fund': self.parse_number(tds[9].get_text(strip=True)) if len(tds) > 9 else 0,
                    'other_corporation': self.parse_number(tds[10].get_text(strip=True)) if len(tds) > 10 else 0,
                }
                rows.append(row)

            return rows

        except Exception as e:
            self.log.error(f'Page fetch failed: {e}')
            return []

    def save_to_db(self, market_name, data_list):
        """Save data to DB"""
        created_count = 0
        updated_count = 0

        for row in data_list:
            try:
                # Parse date (25.12.05 -> date object, 2-digit year)
                date = datetime.strptime(row['date'], '%y.%m.%d').date()

                obj, created = MarketTrend.objects.update_or_create(
                    market=market_name,
                    date=date,
                    defaults={
                        'individual': row['individual'],
                        'foreign': row['foreign'],
                        'institution': row['institution'],
                        'financial_investment': row['financial_investment'],
                        'insurance': row['insurance'],
                        'trust': row['trust'],
                        'bank': row['bank'],
                        'other_financial': row['other_financial'],
                        'pension_fund': row['pension_fund'],
                        'other_corporation': row['other_corporation'],
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as e:
                self.log.error(f'Save failed ({row["date"]}): {e}')

        self.log.info(f'[{market_name}] Created: {created_count}, Updated: {updated_count}', success=True)

    def parse_number(self, text):
        """Parse number string"""
        if not text:
            return 0
        cleaned = text.replace(',', '').replace('+', '').strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0
