# -*- coding: utf-8 -*-
import gzip
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stocks.logger import StockLogger


class Command(BaseCommand):
    help = '''
DB 백업 (SQLite)

옵션:
  --dir          (선택) 백업 폴더 (기본값: BASE_DIR/backups)
  --keep-daily   (선택) 날짜 백업 보관 일수 (기본값: 14)
  --keep-weekly  (선택) 일요일 백업 보관 일수 (기본값: 90)
  --no-verify    (선택) 무결성 확인 건너뛰기
  --log-level    (선택) debug / info / warning / error (기본값: info)

예시:
  python manage.py backup_db
  python manage.py backup_db --dir /mnt/backup --keep-daily 30
'''

    # cp 로 복사하면 안 된다. 쓰는 중에 복사하면 찢어진 파일이 나오고,
    # 그 사실을 복구하려 할 때에야 알게 된다.
    #
    # sqlite3 의 온라인 백업 API 를 쓴다. 다른 연결이 쓰는 중에도 일관된
    # 사본을 만들어 준다. 서버에 sqlite3 CLI 가 없어도 파이썬에 들어 있다.
    #
    # VACUUM INTO 도 같은 일을 하면서 빈 공간까지 눌러 주지만, 읽기 트랜잭션을
    # 오래 잡아 배치와 부딪힐 수 있다. 백업 API 는 조금씩 나눠 뜨고 그사이
    # 쓰기가 들어오면 알아서 다시 뜬다.
    PAGES_PER_STEP = 2000

    def add_arguments(self, parser):
        parser.add_argument('--dir', type=str, default=None,
                            help='백업 폴더 (기본값: BASE_DIR/backups)')
        parser.add_argument('--keep-daily', type=int, default=14,
                            help='날짜 백업 보관 일수 (기본값: 14)')
        parser.add_argument('--keep-weekly', type=int, default=90,
                            help='일요일 백업 보관 일수 (기본값: 90)')
        parser.add_argument('--no-verify', action='store_true',
                            help='무결성 확인 건너뛰기')
        StockLogger.add_arguments(parser)

    def handle(self, *args, **options):
        self.log = StockLogger(self.stdout, self.style, options, 'backup_db')

        source = Path(settings.DATABASES['default']['NAME'])
        if not source.exists():
            raise CommandError(f'DB 파일이 없습니다: {source}')

        backup_dir = Path(options['dir']) if options['dir'] else source.parent / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)

        today = date.today()
        final = backup_dir / f'db-{today:%Y%m%d}.sqlite3.gz'
        # 중간 산물. 끝까지 못 가면 남는데, 다음 번에 덮어쓰므로 쌓이지 않는다.
        raw = backup_dir / f'db-{today:%Y%m%d}.sqlite3.part'

        self.log.info(f'원본 {source} ({self.mb(source.stat().st_size)})')
        self.log.info(f'백업 {final}')

        started = time.time()
        try:
            self.copy_db(source, raw)
            if not options['no_verify']:
                self.verify(raw)
            self.compress(raw, final)
        except Exception as e:
            # 반쯤 만들어진 파일을 남기지 않는다. 있으면 다음에 그것을
            # 멀쩡한 백업으로 착각한다.
            raw.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise CommandError(f'백업 실패: {e}')

        elapsed = time.time() - started
        size = final.stat().st_size
        ratio = size / source.stat().st_size * 100
        self.log.info(f'백업 완료 | {self.mb(size)} (원본의 {ratio:.0f}%) | {elapsed:.0f}초',
                      success=True)

        removed, kept = self.prune(backup_dir, today,
                                   options['keep_daily'], options['keep_weekly'])
        self.log.separator()
        self.log.info(f'완료 | 보관 {kept}개, 삭제 {removed}개 | '
                      f'폴더 {self.mb(sum(f.stat().st_size for f in backup_dir.glob("db-*.gz")))}',
                      success=True)

    # ── 뜨기 ────────────────────────────────────────────────────────

    def copy_db(self, source, target):
        target.unlink(missing_ok=True)
        # 원본은 읽기 전용으로 연다. 백업이 원본을 건드릴 일은 없다.
        src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst, pages=self.PAGES_PER_STEP, progress=self.progress)
        finally:
            dst.close()
            src.close()
        self.log.debug(f'  사본 {self.mb(target.stat().st_size)}')

    def progress(self, status, remaining, total):
        if total and remaining % (self.PAGES_PER_STEP * 20) < self.PAGES_PER_STEP:
            done = (total - remaining) / total * 100
            self.log.debug(f'  뜨는 중 {done:.0f}%')

    def verify(self, path):
        """받아 둔 것이 멀쩡한지 본다.

        quick_check 를 쓴다. integrity_check 는 모든 쪽을 다 훑어 수백 MB
        에서는 오래 걸린다. 날마다 돌 것이라 빠른 쪽이 맞다 — 찢어진 파일은
        quick_check 로도 걸린다.
        """
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            result = conn.execute('PRAGMA quick_check').fetchone()[0]
        finally:
            conn.close()
        if result != 'ok':
            raise RuntimeError(f'무결성 확인 실패: {str(result)[:200]}')
        self.log.debug('  무결성 확인 ok')

    def compress(self, raw, final):
        # gzip -1. 338M 이 100M 쯤 된다. 더 세게 눌러도 몇 MB 더 줄 뿐인데
        # 시간은 몇 배가 든다.
        with open(raw, 'rb') as fin, gzip.open(final, 'wb', compresslevel=1) as fout:
            shutil.copyfileobj(fin, fout, length=4 * 1024 * 1024)
        raw.unlink()

    # ── 지우기 ──────────────────────────────────────────────────────

    def prune(self, backup_dir, today, keep_daily, keep_weekly):
        """날짜 것은 keep_daily, 일요일 것은 keep_weekly 만큼 둔다.

        두 단으로 두는 까닭: 오늘 고친 ETF 처럼 넉 달 만에 드러나는 고장이
        있다. 2주치만 두면 '언제부터 틀렸나' 를 되짚을 수가 없다.
        """
        removed = kept = 0
        for path in sorted(backup_dir.glob('db-*.sqlite3.gz')):
            try:
                when = datetime.strptime(path.stem.split('-')[1][:8], '%Y%m%d').date()
            except (IndexError, ValueError):
                self.log.warning(f'  이름을 읽지 못해 건드리지 않음: {path.name}')
                continue
            age = (today - when).days
            limit = keep_weekly if when.weekday() == 6 else keep_daily
            if age > limit:
                path.unlink()
                removed += 1
                self.log.debug(f'  삭제 {path.name} ({age}일)')
            else:
                kept += 1
        return removed, kept

    def mb(self, n):
        return f'{n / 1024 / 1024:.0f}MB'
