# 로그 정리 (logrotate)

## 왜

```
stocks.log         177M
daily_update.log    85M
weekly_update.log  6.4M
daum_update.log    750K
                  ─────
                   269M
```

디스크가 모자란 것은 아니다 — 26G 중 12G 가 남아 있다. 문제는 **열어볼 수
없다**는 것이다. 177M 짜리 파일은 `tail` 말고는 손대기 어렵고, 문제가
생겼을 때 들여다보는 것이 로그의 존재 이유다.

## 넣기

```bash
cp deploy/logrotate/jstocks /etc/logrotate.d/jstocks
chmod 644 /etc/logrotate.d/jstocks

logrotate -d /etc/logrotate.d/jstocks    # 시늉만 — 아무것도 바꾸지 않는다
logrotate -f /etc/logrotate.d/jstocks    # 한 번 강제로
ls -lh /home/stock/jstocks/logs/
```

그 뒤로는 우분투의 `logrotate.timer` 가 하루 한 번 알아서 돈다.

## 어떻게 쌓이나

```
stocks.log        지금 쓰는 것
stocks.log.1      어제 것 (압축 안 함 — 바로 볼 일이 많다)
stocks.log.2.gz   그제 것
   ⋮
stocks.log.14.gz  2주 전. 이보다 오래된 것은 지운다
```

첫 로테이션에서 177M 이 `.1` 로 옮겨지고, 다음 날 압축되며 20M 안쪽으로
줄어든다. 텍스트 로그는 보통 열 배 가까이 줄어든다.

## copytruncate 를 쓰는 까닭

보통은 이름을 바꾸고 새 파일을 만든다. 그러면 그 파일을 **이미 열고 있던
프로세스는 이름 바뀐 쪽에 계속 쓴다.** 새 파일은 영영 비어 있게 된다.

배치가 도는 중(15:40 · 19:40 · 금 23:00)에 로테이션이 겹치면 그 일이
생긴다. `*_update.log` 는 셸이 `>>` 로 열어 배치 내내 붙잡고 있다.

`copytruncate` 는 복사한 뒤 원본을 비우므로 그 문제가 없다. 복사와 비우기
사이에 쓰인 몇 줄을 잃을 수 있지만, 로그가 통째로 끊기는 것보다 낫다.

> gunicorn 은 이 파일들을 붙잡고 있지 않다(`/proc/<pid>/fd` 로 확인했다).
> `StockLogger` 는 관리 명령에서만 열고 명령이 끝나면 닫는다.

## 로그 말고 커지는 것

```
db.sqlite3                   338M
db.sqlite3.backup-20260818   309M   ← 석 달 전 것
```

백업이 석 달째 그대로다. 로테이션과는 별개 문제이고 여기서 다루지 않는다.
