# 04. Sprint 2 — 보고서 비동기 처리 파이프라인

> **목표:** 사용자가 `POST /reports`로 보고서 생성을 요청하면 즉시 202를 받고,
> Python Worker가 비동기로 Phase 4 `ReportOrchestrator.generate()`를 실행하여
> 진행률을 SSE로 스트리밍하고 완료 시 Markdown을 MinIO에 저장한다.
>
> **선행 조건:** Sprint 1 완료, 마이그레이션 0003/0004 적용

---

## 1. 산출물

- `internal/report/`, `internal/queue/`, `internal/storage/` 패키지
- 6개 HTTP 엔드포인트 (CRUD + SSE + Markdown 다운로드)
- `python/worker/` Python Worker 코드 일체 (레포 내장)
- E2E: 골든 주소 3개 생성 → 완료까지 60-90초 이내 통과

---

## 2. Redis Streams 컨트랙트 (Go ↔ Python 합의)

이 컨트랙트는 Go API와 Python Worker가 **공유**하는 메시지 형식이다. 변경 시 양쪽을 동시에 수정.

### 2.1 큐 구조

```
Stream:        realtor:reports
Consumer Group: workers
Consumer Name: worker-{hostname}-{pid}  (Worker 시작 시 자동 생성)

XADD 시 필드:
  report_id      : UUID (string)
  user_id        : UUID (string)
  address_input  : 사용자 원본 입력 (string)
  candidate_json : 인터뷰 Step 2에서 선택된 AddressCandidate (JSON string, 옵션)
  purpose        : "매매_실거주" 등 (string)
  custom_notes   : 사용자 메모 (string, 옵션)
  enqueued_at    : RFC3339 timestamp (string)
```

### 2.2 진행률 채널

```
Channel:  report:progress:{report_id}
Payload (JSON):
{
  "step":     "데이터 수집",
  "detail":   "실거래가 API 조회 중...",
  "percent":  30,
  "timestamp": "2026-04-08T10:00:30.123Z"
}
```

특수 이벤트:
- `step="완료"`, `percent=100`, `markdown_url="..."` — 보고서 완료
- `step="에러"`, `error="..."` — 보고서 실패

### 2.3 Stream 메시지 ACK 정책

- Worker가 보고서 생성을 **시작**하면 곧바로 `XACK`하지 않는다 (재시도 위해)
- 성공 완료 → `XACK`
- 영구 실패(재시도 불가) → `XACK` + `status=failed` 기록
- 일시적 실패(네트워크 등) → `XACK`하지 않음 → 다음 Worker가 `XPENDING` + `XCLAIM`으로 재처리
- pending 메시지 모니터링: `XPENDING realtor:reports workers` 주기적 확인

> Sprint 2에서는 단일 Worker로 시작. `XCLAIM` 기반 재시도 메커니즘은 Sprint 2 끝에 간단한 구현만 추가하고,
> 정교한 dead-letter queue는 Phase 5-2에서 다룸.

---

## 3. Go API 엔드포인트

### 3.1 `POST /api/v1/reports`

**인증 필요.**

**Request:**
```json
{
  "address_input": "마포래미안푸르지오 101동 1502호",
  "candidate": {
    "place_name": "마포래미안푸르지오",
    "address_name": "서울 마포구 아현동 699",
    "road_address": "서울 마포구 마포대로 217",
    "lat": 37.554,
    "lng": 126.951
  },
  "purpose": "매매_실거주",
  "custom_notes": ""
}
```

`candidate`는 옵션. 없으면 Worker가 자체적으로 주소 정규화 수행.
`purpose`는 enum 검증: `매매_실거주`, `매매_투자`, `매도`, `전세`, `경매`, `기타`

**처리:**
1. `RequireAuth` 미들웨어로 user_id 추출
2. Rate Limit 검사 (`rl:report:{user_id}`, 5/min)
3. `auth.Service.GetUserByID()` → 크레딧 검사 (`credits_remaining >= 1`이거나 tier=pro)
4. 트랜잭션 시작:
   - `INSERT INTO reports (..., status='pending', progress_percent=0)` → `report_id`
   - `UPDATE users SET credits_remaining = credits_remaining - 1` (free/basic 한정)
   - `INSERT INTO credit_ledger (..., delta=-1, reason='report_generation')`
5. 트랜잭션 커밋
6. `XADD realtor:reports * report_id ... user_id ...` → `job_id`
7. `UPDATE reports SET job_id=$1 WHERE id=$2`
8. 응답:

**Response 202:**
```json
{
  "report_id": "uuid",
  "job_id": "1712574000000-0",
  "status": "pending",
  "progress_url": "/api/v1/reports/{id}/progress",
  "credits_remaining": 1
}
```

**Errors:**
- 400 `invalid_purpose`, `address_input_required`
- 402 `insufficient_credits`
- 429 `rate_limit_exceeded`

> **트랜잭션 + 큐 발행 순서:** 큐 발행 실패 시 크레딧을 환불해야 한다.
> 구현: XADD 실패 시 별도 트랜잭션으로 credit_ledger에 +1 추가 + reports.status='failed' 기록.
> Outbox 패턴은 Phase 5-2에서 도입.

---

### 3.2 `GET /api/v1/reports`

**인증 필요. 본인 보고서만.**

**Query:** `?status=completed&limit=20&cursor=2026-04-08T10:00:00Z`

**Response 200:**
```json
{
  "reports": [
    {
      "id": "uuid",
      "address_input": "...",
      "purpose": "매매_실거주",
      "status": "completed",
      "progress_percent": 100,
      "created_at": "...",
      "completed_at": "..."
    }
  ],
  "next_cursor": "2026-04-08T09:30:00Z"
}
```

---

### 3.3 `GET /api/v1/reports/{id}`

**인증 필요. 본인 소유 검증.**

**Response 200:**
```json
{
  "id": "uuid",
  "address_input": "...",
  "normalized_address": { ... },
  "purpose": "매매_실거주",
  "status": "completed",
  "progress_percent": 100,
  "current_step": "완료",
  "sections": [
    { "section_type": "price", "content": "...markdown..." },
    { "section_type": "location", "content": "..." }
  ],
  "markdown_url": "https://localhost:9000/realtor-reports/...",
  "generation_time_ms": 45230,
  "created_at": "...",
  "completed_at": "..."
}
```

처리 중인 경우 sections는 부분만 포함 (Worker가 섹션별로 INSERT).

---

### 3.4 `GET /api/v1/reports/{id}/progress` (SSE)

**인증 필요. 본인 소유 검증.**

**Headers:**
```
Cache-Control: no-cache
Content-Type: text/event-stream
Connection: keep-alive
X-Accel-Buffering: no
```

**처리:**
1. DB에서 현재 status 조회
2. 이미 completed/failed면 마지막 이벤트 1건 + 종료
3. 아니면 Redis `SUBSCRIBE report:progress:{id}` 시작
4. 메시지 수신 시 SSE 형식으로 변환:
   ```
   event: progress
   data: {"step":"데이터 수집","detail":"...","percent":30}

   ```
5. percent=100 또는 step="에러" 수신 시 종료
6. 클라이언트 연결 끊김 감지 → unsubscribe + goroutine 정리

**SSE 구현 패턴 (`internal/sse/`):**

```go
type Stream struct {
    rdb      *redis.Client
    reportID uuid.UUID
}

func (s *Stream) Pipe(ctx context.Context, w http.ResponseWriter) error {
    flusher, ok := w.(http.Flusher)
    if !ok {
        return errors.New("streaming not supported")
    }
    pubsub := s.rdb.Subscribe(ctx, "report:progress:"+s.reportID.String())
    defer pubsub.Close()

    // 초기 상태 1건 (DB에서 조회) 전송
    // ...

    ch := pubsub.Channel()
    for {
        select {
        case <-ctx.Done():
            return nil
        case msg, ok := <-ch:
            if !ok {
                return nil
            }
            fmt.Fprintf(w, "event: progress\ndata: %s\n\n", msg.Payload)
            flusher.Flush()
            if isTerminal(msg.Payload) {
                return nil
            }
        }
    }
}
```

> **유의:** 동일 보고서를 여러 클라이언트가 동시에 SUBSCRIBE할 수 있어야 한다.
> Redis PubSub은 fan-out 기본 제공. Worker는 PUBLISH 한 번이면 다수 구독자에게 도달.

---

### 3.5 `GET /api/v1/reports/{id}/markdown`

**인증 필요. 본인 소유 검증. status=completed 필요.**

MinIO 또는 Cloud Storage에서 presigned URL 발급 후 302 redirect.

**Response 302:**
```
Location: http://localhost:9000/realtor-reports/{report_id}/report.md?X-Amz-...
```

URL TTL: 4시간

---

### 3.6 `DELETE /api/v1/reports/{id}`

**인증 필요. 본인 소유 검증.**

처리 중(`pending`/`processing`)인 보고서는 취소 → status=cancelled, Worker가 다음 진행률 갱신 시 감지하면 abort (best-effort).
완료된 보고서는 hard delete + MinIO 파일 삭제.

**Response 204**

---

## 4. Python Worker 구조

### 4.1 진입점 (`__main__.py`)

```python
"""
python -m worker

Redis Streams 'realtor:reports' 컨슈머.
python/report/orchestrator.py의 ReportOrchestrator.generate()를 호출한다.
"""
import asyncio
import logging
import os
import sys

# sys.path.insert 불필요 — PYTHONPATH=/app/python 이 docker-compose에서 설정됨

from worker.consumer import run

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

if __name__ == "__main__":
    asyncio.run(run())
```

### 4.2 Consumer (`consumer.py`)

```python
import asyncio
import json
import os
import socket
import uuid

import redis.asyncio as redis_async

from worker.job import process_job

STREAM = "realtor:reports"
GROUP = "workers"
CONSUMER = f"worker-{socket.gethostname()}-{os.getpid()}"

async def run():
    rdb = redis_async.from_url(os.environ["REDIS_URL"])
    await ensure_group(rdb)

    while True:
        try:
            messages = await rdb.xreadgroup(
                GROUP, CONSUMER,
                streams={STREAM: ">"},
                count=1,
                block=5000,
            )
            if not messages:
                continue
            for _, msgs in messages:
                for msg_id, fields in msgs:
                    await handle_message(rdb, msg_id, fields)
        except Exception as e:
            logging.exception("consumer loop error: %s", e)
            await asyncio.sleep(1)

async def ensure_group(rdb):
    try:
        await rdb.xgroup_create(STREAM, GROUP, id="$", mkstream=True)
    except redis_async.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

async def handle_message(rdb, msg_id, fields):
    decoded = {k.decode(): v.decode() for k, v in fields.items()}
    report_id = decoded["report_id"]
    try:
        await process_job(rdb, decoded)
        await rdb.xack(STREAM, GROUP, msg_id)
    except RetryableError:
        # XACK하지 않음 → XPENDING으로 남아 다음 Worker가 재시도
        logging.warning("retryable error for report %s", report_id)
    except Exception as e:
        logging.exception("permanent failure for report %s: %s", report_id, e)
        await mark_failed(report_id, str(e))
        await rdb.xack(STREAM, GROUP, msg_id)
```

### 4.3 Job 처리 (`job.py`)

```python
import json
import time
import uuid
from datetime import datetime

from worker.config import settings
from worker.persistence import (
    update_progress, insert_section, mark_completed, mark_failed
)
from worker.progress import make_progress_callback
from worker.storage import upload_markdown

# 기존 Phase 4 모듈
from report.orchestrator import ReportOrchestrator
from report.state import UserContext
from api.clients.kakao import KakaoMapClient
from api.clients.real_transaction import RealTransactionClient
from api.clients.building_register import BuildingRegisterClient
from api.clients.land_use import LandUseRegulationClient
from generation.llm_client import create_llm_client

# 1회 초기화 (Worker 프로세스 lifetime)
_kakao = KakaoMapClient()
_transaction = RealTransactionClient()
_building = BuildingRegisterClient()
_land_use = LandUseRegulationClient()
_llm = create_llm_client()
_orchestrator = ReportOrchestrator(
    kakao=_kakao,
    transaction=_transaction,
    building=_building,
    llm=_llm,
    land_use=_land_use,
)


async def process_job(rdb, fields: dict):
    report_id = fields["report_id"]
    user_input = fields["address_input"]
    purpose = fields.get("purpose", "매매_실거주")
    custom_notes = fields.get("custom_notes", "")
    candidate_json = fields.get("candidate_json", "")

    user_context = UserContext(purpose=purpose, custom_notes=custom_notes)
    candidate = parse_candidate(candidate_json) if candidate_json else None

    on_progress = make_progress_callback(rdb, report_id)
    await update_status(report_id, "processing")

    started = time.monotonic()
    try:
        state = await _orchestrator.generate(
            user_input=user_input,
            user_context=user_context,
            selected_candidate=candidate,
            on_progress=on_progress,
        )

        # 섹션을 DB에 저장
        for section_type, content in state.sections.items():
            await insert_section(report_id, section_type, content, state.chart_images)

        # Markdown 조립
        markdown = _orchestrator.assemble_report(state)
        markdown_url = await upload_markdown(report_id, markdown)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        await mark_completed(report_id, markdown_url, elapsed_ms)

        # 최종 이벤트
        await on_progress("완료", f"보고서 생성 완료 ({elapsed_ms/1000:.1f}초)", percent=100,
                          markdown_url=markdown_url)
    except Exception as e:
        await mark_failed(report_id, str(e))
        await on_progress("에러", str(e), percent=0, error=str(e))
        raise
```

### 4.4 진행률 콜백 (`progress.py`)

`ReportOrchestrator._notify` 시그니처는 `(step: str, detail: str)`.
이를 Redis PUBLISH로 매핑하면서 percent도 자동 부여한다:

```python
import json
from datetime import datetime, timezone

from worker.persistence import update_progress

# Phase 4 _notify step → 진행률 percent 매핑
STEP_PERCENT = {
    "주소 정규화": 10,
    "데이터 수집": 30,
    "차트 생성": 45,
    "세금/대출 계산": 50,
    "보고서 생성": 75,
    "요약 생성": 90,
    "완료": 100,
    "에러": 0,
}

def make_progress_callback(rdb, report_id: str):
    async def callback(step: str, detail: str = "", **extra):
        percent = extra.get("percent", STEP_PERCENT.get(step, 0))
        payload = {
            "step": step,
            "detail": detail,
            "percent": percent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        payload.update({k: v for k, v in extra.items() if k != "percent"})

        await rdb.publish(f"report:progress:{report_id}", json.dumps(payload))
        await update_progress(report_id, step, percent)

    return callback
```

> ⚠️ Phase 4의 `ReportOrchestrator._notify`는 동기 호출이다. 비동기 콜백을 받기 위해
> 어댑터를 만들거나 Phase 4 코드를 약간 수정해야 할 수 있다. 이 작업은 Sprint 2 진행 중 첫째 날에
> 확인하고, Phase 4 코드 수정이 필요하면 별도 PR로 처리한다.

### 4.5 Persistence (`persistence.py`)

```python
import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ["DATABASE_URL"]

async def _conn():
    return await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row)

async def update_status(report_id: str, status: str):
    async with await _conn() as conn:
        await conn.execute(
            "UPDATE reports SET status=%s, started_at=COALESCE(started_at, NOW()) WHERE id=%s",
            (status, report_id),
        )
        await conn.commit()

async def update_progress(report_id: str, step: str, percent: int):
    async with await _conn() as conn:
        await conn.execute(
            "UPDATE reports SET current_step=%s, progress_percent=%s, updated_at=NOW() WHERE id=%s",
            (step, percent, report_id),
        )
        await conn.commit()

async def insert_section(report_id: str, section_type: str, content: str, chart_images: dict):
    chart_keys = [k for k in chart_images.keys()]  # base64는 MinIO에 별도 업로드 후 URL로 교체할 수도 있음
    async with await _conn() as conn:
        await conn.execute(
            """
            INSERT INTO report_sections (report_id, section_type, content, chart_urls)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (report_id, section_type, content, '[]'),  # chart_urls는 Sprint 2 마지막에 처리
        )
        await conn.commit()

async def mark_completed(report_id: str, markdown_url: str, elapsed_ms: int):
    async with await _conn() as conn:
        await conn.execute(
            """
            UPDATE reports
            SET status='completed', progress_percent=100, current_step='완료',
                markdown_url=%s, generation_time_ms=%s, completed_at=NOW(), updated_at=NOW()
            WHERE id=%s
            """,
            (markdown_url, elapsed_ms, report_id),
        )
        await conn.commit()

async def mark_failed(report_id: str, error_message: str):
    async with await _conn() as conn:
        await conn.execute(
            """
            UPDATE reports
            SET status='failed', error_message=%s, updated_at=NOW()
            WHERE id=%s
            """,
            (error_message[:2000], report_id),
        )
        await conn.commit()
```

> 매번 connection을 새로 여는 것은 단순함을 위함. Sprint 2 막바지에 `psycopg_pool`로 풀링 도입 검토.

### 4.6 Storage (`storage.py`)

```python
import os
from minio import Minio
from io import BytesIO

_client = Minio(
    endpoint=os.environ["STORAGE_ENDPOINT"].replace("http://", "").replace("https://", ""),
    access_key=os.environ["STORAGE_ACCESS_KEY"],
    secret_key=os.environ["STORAGE_SECRET_KEY"],
    secure=False,  # 로컬 MinIO
)
BUCKET = os.environ.get("STORAGE_BUCKET_REPORTS", "realtor-reports")

async def upload_markdown(report_id: str, markdown: str) -> str:
    data = markdown.encode("utf-8")
    key = f"{report_id}/report.md"
    _client.put_object(
        BUCKET, key,
        data=BytesIO(data),
        length=len(data),
        content_type="text/markdown; charset=utf-8",
    )
    return key  # Go API가 presigned URL을 발급할 때 이 키를 사용
```

### 4.7 Worker 시작 명령

`docker-compose.yml`의 `python-worker` 서비스 `command`를 다음과 같이 변경:

```yaml
command: >
  bash -c '
    pip install --quiet -r /app/python/requirements.txt &&
    python -m worker
  '
```

> `PYTHONPATH=/app/python` 이 설정되어 있으므로 `python -m worker`로 `python/worker/__main__.py` 실행.
> 또는 더 깔끔하게: 별도 `Dockerfile`을 작성하여 Sprint 2 종료 시 빌드 이미지로 전환.

---

## 5. LLM 백엔드 (CLI 모드)

`LLM_BACKEND=cli`로 동작 (이미 .env.example 기본값).

[python/generation/llm_client.py](../../codes/realtor-ai-backend/python/generation/llm_client.py) `create_llm_client()`이
`params.yaml` + 환경변수에서 backend를 읽어 `CLILLMClient`를 반환한다.

CLILLMClient는 호스트의 `/usr/local/bin/claude-code` 바이너리를 subprocess로 호출한다.

### 5.1 컨테이너에서 Claude Code CLI 사용

Python Worker 컨테이너 안에서 host의 `/usr/local/bin/claude-code`를 사용하려면 마운트가 필요하다.
docker-compose.yml에 추가:

```yaml
python-worker:
  volumes:
    - ${GO_API_SRC_PATH}/python:/app/python
    - /usr/local/bin/claude-code:/usr/local/bin/claude-code:ro  # 추가
    - /home/gon/.config/claude:/root/.config/claude:ro          # 인증 정보 (필요 시)
```

> **대안:** 호스트에서 worker를 직접 실행 (`python -m worker`)하고 컨테이너는 인프라만.
> Sprint 2 첫날 어떤 방식이 더 매끄러운지 결정.

---

## 6. 진행률 매핑 (Phase 4 `_notify` → percent)

| Phase 4 step | percent | 비고 |
|-------------|---------|------|
| 주소 정규화 | 10 | Stage 0 |
| 데이터 수집 | 30 | Stage 1 — 13개 API 병렬 |
| 차트 생성 | 45 | matplotlib |
| 세금/대출 계산 | 50 | 룰엔진 |
| 보고서 생성 | 75 | LLM 4섹션 병렬 |
| 요약 생성 | 90 | Executive summary |
| 완료 | 100 | |
| 에러 | 0 | 실패 |

이 매핑은 `progress.py`의 `STEP_PERCENT` 딕셔너리에 단일 정의.

---

## 7. 검증

### 7.1 단위 테스트

- `internal/report/service_test.go`: 크레딧 차감 트랜잭션, 큐 발행 실패 시 환불
- `internal/report/sse_test.go`: 가짜 Redis로 SSE 스트림 변환 검증
- `internal/queue/stream_test.go`: XADD/XREADGROUP round-trip
- `worker/tests/test_progress_mapping.py`: STEP_PERCENT 매핑
- `worker/tests/test_consumer.py`: mock Redis로 메시지 라우팅

### 7.2 통합 테스트

`tests/integration/report_pipeline_test.go`:
1. 사용자 가입 → 크레딧 2건
2. `POST /reports` (mock 주소) → 202 + report_id
3. (별도 goroutine) Worker가 처리하도록 잠시 대기
4. SSE 구독 → 7단계 이벤트 수신 검증
5. status=completed 확인
6. `GET /reports/{id}` → sections 7개 존재
7. `GET /reports/{id}/markdown` → 302 + MinIO에서 다운로드 가능

### 7.3 E2E 골든 주소 시나리오

`tests/e2e/reports_test.sh`:

```bash
ADDRESSES=(
    "마포래미안푸르지오 101동 1502호"
    "강남구 역삼동 개나리아파트 105동"
    "부산광역시 해운대구 우동 두산위브더제니스 201동"
)

for addr in "${ADDRESSES[@]}"; do
    echo "=== Testing: $addr ==="
    REPORT_ID=$(curl -sf -X POST $BASE/reports \
        -H "Authorization: Bearer $TOKEN" \
        -H 'Content-Type: application/json' \
        -d "{\"address_input\":\"$addr\",\"purpose\":\"매매_실거주\"}" \
        | jq -r .report_id)

    # SSE 구독 (90초 timeout)
    timeout 90 curl -sN -H "Authorization: Bearer $TOKEN" \
        $BASE/reports/$REPORT_ID/progress | tee /tmp/sse-$REPORT_ID.log

    # 최종 status 확인
    STATUS=$(curl -sf -H "Authorization: Bearer $TOKEN" \
        $BASE/reports/$REPORT_ID | jq -r .status)
    [[ "$STATUS" == "completed" ]] || { echo "FAIL: $addr ended with $STATUS"; exit 1; }
done
```

### 7.4 Sprint 2 종료 체크리스트

- [ ] 마이그레이션 0003, 0004 적용 + sqlc 생성
- [ ] 6개 엔드포인트 구현 + 단위 테스트
- [ ] Worker 프로세스가 Redis Stream에서 메시지 컨슘
- [ ] Worker가 `ReportOrchestrator.generate()`를 정상 호출 (LLM_BACKEND=cli)
- [ ] 진행률 7단계가 SSE로 도달
- [ ] 골든 주소 3개 모두 status=completed (90초 이내)
- [ ] Markdown이 MinIO에 저장 + presigned URL로 다운로드 가능
- [ ] 보고서 생성 중 Worker 강제 종료 → restart → pending 복구 확인 (XPENDING)
- [ ] 크레딧 부족 시 402, 큐 발행 실패 시 환불 동작
- [ ] `go test ./internal/report/... -race` 통과
- [ ] Worker pytest 통과
