# Phase 5-1 Backend Development — 전체 개요

> **최종 업데이트:** 2026-04-12
> **상태:** 기획 완료, 구현 대기
> **전제 환경:** Phase 5-0 로컬 Docker Compose ([03_local_docker_dev_environment.md](../5_0_infra_setting/03_local_docker_dev_environment.md))

---

## 1. Context — 왜 이 작업이 필요한가

Phase 4(딥 리포트 시스템)는 단일 Python 프로세스 + Chainlit UI로 동작 검증이 끝났다.
Phase 5의 목표는 이를 GCP 프로덕션 웹 서비스로 전환하는 것이며, **Phase 5-1**은 그 첫 단계로
**로컬 Docker Compose 환경에서 동작하는 Go API + Python Worker 백엔드**를 구현하는 작업이다.

핵심 전환:

| 항목 | Phase 4 (현재) | Phase 5-1 (이번 단계) |
|------|---------------|---------------------|
| 진입점 | `python codes/report/cli.py` 또는 Chainlit UI | Go HTTP API (`POST /api/v1/reports`) |
| 인증 | 없음 | JWT + 카카오/네이버/Google OAuth |
| 사용자 관리 | 없음 | PostgreSQL `users` 테이블 |
| 보고서 호출 | 동기 (사용자가 끝까지 대기) | **비동기** (Redis Streams + Worker) |
| 진행 상태 | 콘솔 print | **SSE** (`GET /reports/{id}/progress`) |
| 보고서 저장 | 로컬 파일 | PostgreSQL + MinIO |
| 보고서 생성 코드 | `ReportOrchestrator.generate()` 직접 호출 | **Python Worker가 동일 함수를 래핑** |

> **중요:** Phase 4의 Python 코드(`report/`, `api/`, `rules/`, `generation/`, `query/`)는
> `codes/realtor-ai-backend/python/` 안에 **복사·내장**되어 있다.
> 이를 통해 Go 백엔드 레포 하나로 클라우드 배포 시 독립적으로 동작할 수 있다.
> Python Worker는 같은 레포의 `python/worker/` 에 위치하며, `python/report/orchestrator.py`를 직접 import한다.
> (PYTHONPATH를 `python/`으로 설정하여 기존 import 경로 `from api.xxx`, `from report.xxx` 가 그대로 유지됨)

### 본 단계에서 다루지 않는 것

- GCP 배포 (Phase 5-2)
- Next.js 프론트엔드 (Phase 5-3)
- PDF 생성 (Sprint 2에서는 Markdown만, PDF는 Phase 5-2)
- 모니터링 대시보드 (Phase 5-2 GCP에서 GMP/Cloud Trace 연결)

---

## 2. 사용자 결정 사항 (2026-04-08 확정)

| 항목 | 결정 | 배경 |
|------|------|------|
| **5-1 범위** | Go API + Python Worker 래퍼 | 로컬 Docker에서 E2E 흐름이 동작해야 의미 있음 |
| **Go 코드 위치** | `/home/gon/ws/rag/codes/realtor-ai-backend/` | rag 트리 안에 두되 별도 git 레포로 init |
| **LLM 백엔드** | `LLM_BACKEND=cli` | Claude Code CLI 사용, 로컬 비용 $0 |
| **결제** | Toss Payments 테스트 모드 stub | 실제 계약 없이 통합 흐름 검증 |
| **MVP 우선** | **Sprint 1: Auth** 부터 | 다른 모든 기능의 전제 |

---

## 3. Sprint 로드맵

본 5-1은 4개 Sprint + 사전 준비 단계로 진행한다. 각 Sprint는 검증 체크리스트를 통과해야 다음으로 진행.

```
Sprint 0 (1일): 레포 골격
  ├─ codes/realtor-ai-backend/ git init
  ├─ go.mod + cmd/server/main.go (헬스체크 1개)
  ├─ .air.toml + Dockerfile + Makefile
  └─ docker compose up -d go-api → GET /health 200 OK

Sprint 1 (1주): 인증
  ├─ DB 마이그레이션 (sessions 테이블, users 컬럼 추가)
  ├─ JWT 발급/검증 (jwx)
  ├─ 비밀번호 가입/로그인 (bcrypt)
  ├─ 카카오/네이버/Google OAuth Authorization Code Flow
  ├─ RequireAuth 미들웨어
  └─ 검증: 9개 엔드포인트 curl 시나리오 100% 통과

Sprint 2 (1.5주): 보고서 비동기 처리
  ├─ Redis Streams 컨트랙트 설계
  ├─ Go API: POST /reports + GET /reports/{id} + SSE
  ├─ python/worker/ 작성 (XREADGROUP 컨슈머)
  ├─ Worker → ReportOrchestrator.generate() 호출
  ├─ Worker → Redis PUBLISH 진행률 + Postgres UPDATE
  ├─ 보고서 Markdown → MinIO 업로드
  └─ 검증: 골든 주소 3개 E2E (생성→완료→조회) 통과

Sprint 3 (1주): 주소/사용자/PIPA
  ├─ POST /address/resolve (Kakao Geocoding 직접 호출 + Redis 캐시)
  ├─ /user/profile, /user/usage, /user/data-export, /user/account
  ├─ DB: pipa_audit_log 테이블
  └─ 검증: PIPA 시나리오 (가입→데이터 export→삭제) 통과

Sprint 4 (3-5일): 결제 stub
  ├─ POST /payments/prepare, /confirm, /webhook
  ├─ Toss Payments API 클라이언트 골격 (TOSS_TEST_MODE=true)
  ├─ 크레딧 충전 → users/payments 트랜잭션
  └─ 검증: stub 모드 결제 → 보고서 1건 생성 흐름 통과
```

---

## 4. 핵심 기술 결정

### 4.1 Go 라이브러리 (확정)

| 카테고리 | 선택 | 이유 |
|---------|------|------|
| HTTP 라우터 | `go-chi/chi/v5` | 가볍고 미들웨어 친화적, 표준 `net/http` 호환 |
| DB 쿼리 | `sqlc` (코드 생성) + `jackc/pgx/v5` | 타입세이프 SQL, ORM 회피 |
| DB 마이그레이션 | `golang-migrate/migrate` | SQL 파일 기반, 단순함 |
| Redis 클라이언트 | `redis/go-redis/v9` | Streams/PubSub 모두 지원 |
| JWT | `lestrrat-go/jwx/v2` | JOSE 표준 준수, key rotation 용이 |
| 비밀번호 해시 | `golang.org/x/crypto/bcrypt` | 표준, cost 12 |
| 입력 검증 | `go-playground/validator/v10` | 태그 기반 |
| MinIO 클라이언트 | `minio/minio-go/v7` | S3 호환, GCS 마이그레이션 시 인터페이스로 분리 |
| 환경변수 | `caarlos0/env/v11` | 구조체 태그 기반, 검증 포함 |
| 로깅 | 표준 `log/slog` (Go 1.21+) | 외부 의존성 없음, JSON 핸들러 내장 |
| HTTP 클라이언트 | 표준 `net/http` + `hashicorp/go-retryablehttp` | OAuth/카카오/Toss 호출용 |
| 테스트 | 표준 `testing` + `stretchr/testify` | 간결한 assertion |

### 4.2 Python 코드 (Go 레포에 내장)

Phase 4 Python 코드는 `codes/realtor-ai-backend/python/` 안에 복사·내장되어 **독립 배포 가능한 단일 레포** 구조를 이룬다.

```
codes/realtor-ai-backend/python/
├── api/           # 외부 API 클라이언트 (카카오, 실거래가, 건축물대장, 토지이용규제)
├── generation/    # LLM 클라이언트 (CLI/API 듀얼 모드)
├── query/         # RAG 검색 파이프라인 (Phase 5-2 RAG 통합 시 사용)
├── report/        # 보고서 오케스트레이터, 차트, 프롬프트, config
├── rules/         # 세금/대출 룰엔진 + tax_rates_2026.yaml
├── worker/        # Redis Streams 컨슈머 (Sprint 2에서 구현)
└── requirements.txt
```

| 항목 | 선택 |
|------|------|
| 위치 | `codes/realtor-ai-backend/python/worker/` (Go 레포 내장) |
| 진입점 | `python -m worker` (`__main__.py`) |
| PYTHONPATH | `/app/python` (docker-compose) → `from api.xxx`, `from report.xxx` 그대로 동작 |
| Redis | `redis-py` 5.x |
| Postgres | `psycopg[binary]` 3.x |
| 보고서 생성 | `python/report/orchestrator.ReportOrchestrator.generate()` 호출 |
| LLM | `python/generation/llm_client.create_llm_client()`, `LLM_BACKEND=cli` |

> docker-compose의 `python-worker` 서비스는 `${GO_API_SRC_PATH}/python:/app/python`으로 마운트하고
> `PYTHONPATH=/app/python`으로 설정하여 기존 import 경로가 수정 없이 동작한다.

### 4.3 Redis 사용 패턴 (확정)

| 용도 | 키/스트림 | TTL |
|------|---------|-----|
| 캐시: 주소 정규화 | `addr:resolve:{md5(input)}` | 30일 |
| 캐시: 카카오 Place 검색 | `kakao:place:{md5(query)}` | 7일 |
| Rate limit: 사용자별 보고서 생성 | `rl:report:{user_id}` | 1분 (sliding window) |
| Rate limit: IP별 인증 | `rl:auth:{ip}` | 1분 |
| 잡 큐: 보고서 생성 | Stream `realtor:reports`, Group `workers` | 영속 |
| 진행률 발행 | PubSub `report:progress:{report_id}` | 일시적 |
| Refresh 토큰 (옵션) | `auth:refresh:{user_id}:{jti}` | 7일 |

### 4.4 sqlc + golang-migrate

- 마이그레이션: `migrations/000{N}_{name}.up.sql` + `.down.sql` 쌍
- sqlc 쿼리: `internal/{domain}/queries/*.sql` → `internal/{domain}/db/*.go` 생성
- 첫 마이그레이션은 기존 `init.sql`과 충돌하지 않는 ALTER만 포함 (init.sql은 1회성으로 둠)

---

## 5. Python 코드 (내장) 연동 지점

Phase 4 Python 코드는 `codes/realtor-ai-backend/python/` 안에 내장되어 있다.
Worker는 이 코드를 직접 import하여 사용한다.

| 모듈 | 레포 내 경로 | 5-1에서의 사용 |
|------|------------|-------------|
| `ReportOrchestrator.generate()` | [python/report/orchestrator.py](../../codes/realtor-ai-backend/python/report/orchestrator.py) | Worker가 메시지 1건당 1회 호출 |
| `_notify(step, detail)` 콜백 | [python/report/orchestrator.py](../../codes/realtor-ai-backend/python/report/orchestrator.py) | Worker가 Redis PUBLISH로 매핑 |
| `create_llm_client()` | [python/generation/llm_client.py](../../codes/realtor-ai-backend/python/generation/llm_client.py) | `LLM_BACKEND=cli`로 자동 분기, 코드 변경 없음 |
| `KakaoMapClient` | [python/api/clients/kakao.py](../../codes/realtor-ai-backend/python/api/clients/kakao.py) | Worker는 그대로, Go API는 `internal/api/kakao.go`로 즉시 응답용 재구현 |
| `RealTransactionClient` | [python/api/clients/real_transaction.py](../../codes/realtor-ai-backend/python/api/clients/real_transaction.py) | Worker가 그대로 사용 |
| `BuildingRegisterClient` | [python/api/clients/building_register.py](../../codes/realtor-ai-backend/python/api/clients/building_register.py) | Worker가 그대로 사용 |
| `run_all()` 룰엔진 | [python/rules/engine.py](../../codes/realtor-ai-backend/python/rules/engine.py) | Worker가 그대로 사용 |
| `params.yaml` | [python/report/config/params.yaml](../../codes/realtor-ai-backend/python/report/config/params.yaml) | Worker만 읽음. Go API는 자체 환경변수로 관리 |
| 인터뷰 4단계 흐름 | [python/report/interview.py](../../codes/realtor-ai-backend/python/report/interview.py) | 참조용. Go API가 REST로 노출 (`/address/resolve` + `/reports` 본문) |

> Go API는 인터뷰 흐름을 그대로 복제하지 않는다. 프론트엔드가 단계별로 폼을 보여주고
> 마지막에 한 번에 `POST /reports` 페이로드(address_input + candidate + purpose + custom_notes)를 보낸다.

---

## 6. 하위 문서 가이드

| 문서 | 내용 |
|------|------|
| [01_repo_structure.md](01_repo_structure.md) | Go 레포 디렉토리 구조, Worker 구조, 라이브러리 픽스, 빌드 |
| [02_database_and_migrations.md](02_database_and_migrations.md) | DB 스키마 확장, sqlc/migrate 운영 |
| [03_sprint1_auth.md](03_sprint1_auth.md) | Sprint 1: 인증 시스템 상세 명세 |
| [04_sprint2_report_pipeline.md](04_sprint2_report_pipeline.md) | Sprint 2: 보고서 비동기 처리 + Worker 상세 |
| [05_sprint3_address_user_payment.md](05_sprint3_address_user_payment.md) | Sprint 3+4: 주소/사용자/결제 stub |
| [06_testing_and_observability.md](06_testing_and_observability.md) | 테스트, 로깅, 메트릭 전략 |

---

## 7. 검증 (전체 5-1 종료 조건)

본 단계 전체가 종료되는 시점은 다음 시나리오가 로컬 Docker Compose에서 100% 통과할 때다:

1. **신규 가입**: 카카오 OAuth로 가입 → JWT 발급 → `/auth/me` 200
2. **주소 정규화**: `POST /address/resolve` → 후보 3건 이상 반환
3. **보고서 생성**: `POST /reports` → 202 → SSE 진행률 7단계 수신 → status=completed
4. **보고서 조회**: `GET /reports/{id}` → 본문 + 섹션 + Markdown URL 응답
5. **결제 stub**: `POST /payments/prepare` → `confirm` → 크레딧 충전 → 추가 보고서 생성 가능
6. **PIPA**: `GET /user/data-export` → JSON 다운로드 → `DELETE /user/account` → 이후 로그인 불가
7. **장애 복구**: Worker 컨테이너 강제 종료 → `docker compose restart python-worker` → pending 보고서가 다시 처리됨

위 시나리오는 Sprint 4 종료 시점에 전부 통과해야 한다.
