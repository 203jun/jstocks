# backup_db

SQLite DB 를 떠서 압축하고, 오래된 것을 지운다.

## 왜

석 달 동안 백업이 하나뿐이었다(2026-08-18). 그 사이 컬럼을 지우는
마이그레이션(0164)을 돌렸는데, 그때 복구 가능한 가장 최근 시점이 8월이었다.

**되찾을 수 없는 것은 시세가 아니라 사람이 쓴 것이다** — 메모, AI 판단,
리서치, 올려 둔 리포트 PDF, 투자일기, 보유 이력. 시세는 다시 받으면 된다.

## 사용법

```bash
python manage.py backup_db
python manage.py backup_db --dir /mnt/backup --keep-daily 30
```

## 옵션

| 옵션 | 필수 | 설명 |
|------|------|------|
| `--dir` | X | 백업 폴더 (기본: `BASE_DIR/backups`) |
| `--keep-daily` | X | 날짜 백업 보관 일수 (기본: 14) |
| `--keep-weekly` | X | 일요일 백업 보관 일수 (기본: 90) |
| `--no-verify` | X | 무결성 확인 건너뛰기 |
| `--log-level` | X | debug / info / warning / error (기본: info) |

## cp 로 복사하면 안 된다

쓰는 중에 복사하면 찢어진 파일이 나온다. 그리고 **그 사실은 복구하려 할
때에야 알게 된다.**

`sqlite3` 의 온라인 백업 API 를 쓴다. 다른 연결이 쓰는 중에도 일관된 사본을
만들어 준다. 서버에 `sqlite3` CLI 가 없지만 파이썬에 들어 있다(3.37.2).

`VACUUM INTO` 도 같은 일을 하면서 빈 공간까지 눌러 주지만, 읽기 트랜잭션을
오래 잡아 배치와 부딪힐 수 있다. 백업 API 는 조금씩 나눠 뜨고 그사이 쓰기가
들어오면 알아서 다시 뜬다.

뜬 뒤에는 `PRAGMA quick_check` 로 확인하고, 통과해야 압축한다. 실패하면
반쯤 만들어진 파일을 지운다 — 남겨 두면 다음에 멀쩡한 백업으로 착각한다.

## 얼마나 걸리고 얼마나 드나

```
269MB → 85MB (원본의 31%) | 2초
```

`gzip -1` 이다. 더 세게 눌러도 몇 MB 더 줄 뿐인데 시간은 몇 배가 든다.

## 두 단으로 보관한다

| | 보관 |
|---|---|
| 날짜 백업 | 14일 |
| **일요일** 백업 | 90일 |

한 단으로 두면 안 되는 까닭: ETF 대시보드가 넉 달 만에 드러났다. 2주치만
두면 "언제부터 틀렸나" 를 되짚을 수가 없다.

180일치로 시늉해 보면 25개가 남는다 — 최근 15일 + 일요일 10개, 가장 오래된
것이 84일 전. 100MB × 25 ≈ 2.5G 이고 디스크는 12G 남아 있다.

## 복구

```bash
cd /home/stock/jstocks
systemctl stop jstocks
cp db.sqlite3 db.sqlite3.직전                       # 지금 것도 일단 남긴다
gunzip -c backups/db-20261115.sqlite3.gz > db.sqlite3
chown stock:stock db.sqlite3 && chmod 640 db.sqlite3
sudo -u stock venv/bin/python manage.py migrate      # 백업이 오래됐으면
systemctl start jstocks
```

복구가 되는지는 확인해 두었다 — 71개 테이블 행수가 원본과 전부 일치했고
Django 가 그대로 읽었다.

## 실행 주기

날마다 06:00 (주말 포함).

```
0 6 * * * /home/stock/jstocks/backup_db.sh >> /home/stock/jstocks/logs/backup_db.log 2>&1
```

배치가 15:40 · 19:40 에 돈다. 그 전에 떠 두면 배치가 무언가를 망쳤을 때
돌아갈 자리가 생긴다.

주말에도 도는 까닭은 시세가 아니라 메모·AI 판단·리서치 때문이다.

## 아직 안 한 것: 서버 밖으로 내보내기

지금 백업은 **원본과 같은 디스크**에 있다. 마이그레이션 실수나 잘못된
삭제는 막아 주지만, 디스크나 VM 자체가 날아가면 같이 간다.

맥이 평일 20:20 에 서버로 붙으므로(`deploy/mac/`) 그때 주 1회 내려받게 할
수 있다. 100MB 를 받는 데 몇 분 걸린다. 필요해지면 그때 더한다.
