"""
크론잡 실행 명령어

crontab에서 매분 호출되며, 현재 시간에 맞는 작업을 실행합니다.

사용법:
  python manage.py run_cron

crontab 설정:
  * * * * * cd /home/stock/jstocks && /home/stock/jstocks/venv/bin/python manage.py run_cron >> /home/stock/jstocks/logs/cron.log 2>&1
"""

import subprocess
import sys
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = '크론잡 스케줄 확인 및 실행'

    def handle(self, *args, **options):
        from stocks.models import CronJob

        now = timezone.localtime()
        current_time = now.strftime('%H:%M')
        current_weekday = str(now.isoweekday())  # 1=월, 7=일

        self.stdout.write(f'[{now.strftime("%Y-%m-%d %H:%M:%S")}] 크론잡 확인 중...')

        # 현재 시간에 실행할 작업 찾기
        jobs = CronJob.objects.filter(is_active=True)

        for job in jobs:
            job_time = job.run_time.strftime('%H:%M')
            job_weekdays = job.weekdays.split(',')

            # 시간과 요일이 맞는지 확인
            if job_time == current_time and current_weekday in job_weekdays:
                self.run_job(job)

    def run_job(self, job):
        """작업 실행"""
        from stocks.models import CronJob

        self.stdout.write(f'  실행: {job.name} ({job.command})')

        # 실행 상태 업데이트
        job.last_run = timezone.now()
        job.last_result = 'running'
        job.save()

        try:
            # management command 실행
            cmd = [sys.executable, 'manage.py'] + job.command.split()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1시간 타임아웃
            )

            if result.returncode == 0:
                job.last_result = 'success'
                self.stdout.write(self.style.SUCCESS(f'    성공'))
            else:
                job.last_result = 'failure'
                self.stdout.write(self.style.ERROR(f'    실패: {result.stderr[:200]}'))

        except subprocess.TimeoutExpired:
            job.last_result = 'failure'
            self.stdout.write(self.style.ERROR(f'    타임아웃'))

        except Exception as e:
            job.last_result = 'failure'
            self.stdout.write(self.style.ERROR(f'    오류: {str(e)}'))

        job.save()
