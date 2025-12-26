import re
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from stocks.models import InfoETF
from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
ETF 정보 업데이트 (네이버 금융 크롤링)

현재가, 등락률, NAV, 시가총액, 구성종목을 네이버에서 크롤링하여 저장합니다.

옵션:
  --code      (선택) ETF 코드 또는 "all" (기본값: all)
  --log-level (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py save_etf_info
  python manage.py save_etf_info --code 305720
'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--code',
            type=str,
            default='all',
            help='ETF 코드 또는 "all" (기본값: all)'
        )
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        # 로거 초기화
        self.log = StockLogger(self.stdout, self.style, options, 'save_etf_info')

        code = options['code']
        process_all = code.lower() == 'all'

        if process_all:
            self.process_all_etfs()
        else:
            self.process_single_etf(code)

    def process_single_etf(self, etf_code):
        """단일 ETF 처리"""
        try:
            etf = InfoETF.objects.get(code=etf_code)
        except InfoETF.DoesNotExist:
            self.log.error(f'ETF 정보 없음: {etf_code}')
            return

        self.log.info(f'ETF: {etf.name}({etf_code})')
        self.log.separator()

        result = self.fetch_and_save(etf)
        if result:
            self.log.info(f'결과: {result}', success=True)
        else:
            self.log.error('업데이트 실패')

    def process_all_etfs(self):
        """전체 관심 ETF 처리"""
        import time

        etfs = InfoETF.objects.filter(is_active=True)
        total = etfs.count()

        if total == 0:
            self.log.warning('관심 ETF가 없습니다.')
            return

        self.log.info(f'ETF 정보 업데이트 시작 (대상: {total}개)')

        success_count = 0
        error_list = []

        for idx, etf in enumerate(etfs, 1):
            try:
                result = self.fetch_and_save(etf, silent=True)
                if result:
                    self.log.info(f'[{idx}/{total}] {etf.code} {etf.name}: {result}')
                    success_count += 1
                else:
                    self.log.error(f'[{idx}/{total}] {etf.code} {etf.name}: 크롤링 실패')
                    error_list.append((etf.code, etf.name, '크롤링 실패'))
                time.sleep(0.5)  # API 요청 간격
            except Exception as e:
                self.log.error(f'[{idx}/{total}] {etf.code} {etf.name}: 실패 - {str(e)}')
                error_list.append((etf.code, etf.name, str(e)))

        # 최종 리포트
        self.log.separator()
        if error_list:
            self.log.info(f'완료 | 성공: {success_count}개, 오류: {len(error_list)}개', success=True)
            self.log.info('')
            self.log.info('[오류 목록]')
            for code, name, err in error_list:
                self.log.error(f'  {code} {name}: {err}')
        else:
            self.log.info(f'완료 | 성공: {success_count}개', success=True)

    def fetch_and_save(self, etf, silent=False):
        """네이버에서 ETF 정보 크롤링 및 저장"""
        url = f'https://finance.naver.com/item/main.naver?code={etf.code}'
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as e:
            if not silent:
                self.log.error(f'네이버 금융 접속 실패: {str(e)}')
            return None

        soup = BeautifulSoup(response.text, 'lxml')

        # 현재가 추출
        current_price = None
        price_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_today > em > span.blind')
        if price_elem:
            try:
                current_price = int(price_elem.get_text(strip=True).replace(',', ''))
            except:
                pass

        # 등락률 추출
        change_rate = None
        rate_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_exday > em:nth-child(4) > span.blind')
        if rate_elem:
            try:
                rate_text = rate_elem.get_text(strip=True).replace('%', '')
                change_rate = float(rate_text)
                # 하락인지 확인
                down_elem = soup.select_one('#chart_area > div.rate_info > div > p.no_exday > em.no_down')
                if down_elem:
                    change_rate = -abs(change_rate)
            except:
                pass

        # NAV 추출
        nav = None
        nav_elem = soup.select_one('#on_board_last_nav')
        if nav_elem:
            try:
                nav = int(nav_elem.get_text(strip=True).replace(',', ''))
            except:
                pass

        # 시가총액 추출
        market_cap = None
        tab_con1 = soup.select_one('#tab_con1')
        if tab_con1:
            for th in tab_con1.find_all('th'):
                if '시가총액' in th.get_text():
                    td = th.find_next_sibling('td')
                    if td:
                        text = td.get_text(strip=True)
                        total = 0
                        # 조 단위 추출 (1조 = 10000억)
                        jo_match = re.search(r'(\d+)조', text.replace(',', ''))
                        if jo_match:
                            total += int(jo_match.group(1)) * 10000
                        # 억 단위 추출
                        eok_match = re.search(r'(\d+)억', text.replace(',', ''))
                        if eok_match:
                            total += int(eok_match.group(1))
                        market_cap = total if total > 0 else None
                    break

        # 구성종목 추출
        holdings = []
        holdings_rows = soup.select('#content > div.section.etf_asset > table > tbody > tr')
        for row in holdings_rows:
            name_elem = row.select_one('td:first-child')
            ratio_elem = row.select_one('td.per')
            if name_elem and ratio_elem:
                holding_name = name_elem.get_text(strip=True)
                holding_ratio = ratio_elem.get_text(strip=True)
                if holding_name and holding_name != '합계':
                    holdings.append({'name': holding_name, 'ratio': holding_ratio})
            if len(holdings) >= 10:
                break

        # DB 업데이트
        update_fields = ['updated_at']
        changes = []

        if current_price is not None:
            etf.current_price = current_price
            update_fields.append('current_price')
            changes.append(f'현재가={current_price:,}')

        if change_rate is not None:
            etf.change_rate = change_rate
            update_fields.append('change_rate')
            changes.append(f'등락률={change_rate:+.2f}%')

        if nav is not None:
            etf.nav = nav
            update_fields.append('nav')
            changes.append(f'NAV={nav:,}')

        if market_cap is not None:
            etf.market_cap = market_cap
            update_fields.append('market_cap')
            changes.append(f'시총={market_cap:,}억')

        if holdings:
            etf.holdings = holdings
            update_fields.append('holdings')
            changes.append(f'구성종목={len(holdings)}개')

        etf.save(update_fields=update_fields)

        return ', '.join(changes) if changes else '변경없음'
