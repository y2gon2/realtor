# 01. 레포 구조 — Go API + Python Worker

> Phase 5-1의 코드 자산이 어디에 어떻게 배치되는지 정의한다.
> 디렉토리 트리, 라이브러리 픽스, 빌드/실행 명령, 환경변수가 모두 여기에 정리된다.

---

## 1. 단일 레포 구조 — Go + Python 내장

| 구성 | 레포 내 경로 | docker-compose 서비스 |
|------|------------|---------------------|
| **Go API** | `codes/realtor-ai-backend/cmd/`, `internal/` | `go-api` |
| **Python Worker + 보고서 파이프라인** | `codes/realtor-ai-backend/python/` | `python-worker` |

> `realtor-ai-backend` 하나의 git 레포에 Go 코드와 Python 코드가 함께 들어 있다.
> 이를 통해 클라우드 배포 시 이 레포만으로 Go API + Python Worker가 **독립적으로 동작**한다.
> Phase 4의 `codes/report/`, `codes/api/`, `codes/rules/`, `codes/generation/`, `codes/query/`를
> `python/` 아래에 복사·내장했으며, PYTHONPATH를 `python/`으로 설정하여 기존 import 경로가 그대로 유지된다.

### docker-compose와의 연결

[codes/local-infra/docker-compose.yml](../../../../codes/local-infra/docker-compose.yml)에서:
- `go-api`: `${GO_API_SRC_PATH}:/app` 마운트 → Go 코드 전체
- `python-worker`: `${GO_API_SRC_PATH}/python:/app/python` 마운트 + `PYTHONPATH=/app/python`

[.env](../../../../codes/local-infra/.env)에 설정:
```bash
GO_API_SRC_PATH=/home/gon/ws/rag/codes/realtor-ai-backend
```

---

## 2. Go API 디렉토리 트리

```
codes/realtor-ai-backend/
├── .air.toml                    # air hot-reload 설정
├── .gitignore
├── .golangci.yml                # 린터 설정
├── Dockerfile                   # 프로덕션 빌드용 (Phase 5-2에서 사용)
├── Makefile                     # 개발 명령 모음
├── README.md
├── go.mod
├── go.sum
├── sqlc.yaml                    # sqlc 코드 생성 설정
│
├── cmd/
│   └── server/
│       └── main.go              # 진입점: 환경변수 로드, DI, HTTP 서버 시작
│
├── internal/                    # 외부 import 차단 (Go 표준)
│   ├── config/
│   │   └── config.go            # caarlos0/env 구조체, validate()
│   │
│   ├── db/
│   │   ├── pool.go              # pgx pool 생성
│   │   └── tx.go                # 트랜잭션 헬퍼
│   │
│   ├── auth/                    # Sprint 1
│   │   ├── handler.go           # POST /auth/signup, /login, /refresh, /logout, /me
│   │   ├── service.go           # 비즈니스 로직 (JWT 발급, 세션 관리)
│   │   ├── jwt.go               # jwx 래퍼
│   │   ├── password.go          # bcrypt 래퍼
│   │   ├── oauth/
│   │   │   ├── provider.go      # OAuthProvider 인터페이스
│   │   │   ├── kakao.go
│   │   │   ├── naver.go
│   │   │   └── google.go
│   │   ├── queries/
│   │   │   ├── users.sql
│   │   │   └── sessions.sql
│   │   └── db/                  # sqlc 자동 생성
│   │       ├── models.go
│   │       ├── users.sql.go
│   │       └── sessions.sql.go
│   │
│   ├── user/                    # Sprint 3
│   │   ├── handler.go           # GET/PUT /user/profile, /usage, /data-export, DELETE /user/account
│   │   ├── service.go
│   │   ├── pipa.go              # 데이터 export, 30일 grace delete 잡
│   │   ├── queries/
│   │   │   └── users.sql
│   │   └── db/
│   │
│   ├── report/                  # Sprint 2
│   │   ├── handler.go           # POST/GET /reports, SSE /progress, GET /pdf
│   │   ├── service.go           # 크레딧 검사 → DB INSERT → Stream XADD
│   │   ├── sse.go               # Redis PubSub → SSE 변환
│   │   ├── queries/
│   │   │   ├── reports.sql
│   │   │   └── sections.sql
│   │   └── db/
│   │
│   ├── address/                 # Sprint 3
│   │   ├── handler.go           # POST /address/resolve
│   │   ├── service.go           # Kakao 호출 + 캐시
│   │   └── normalizer.go        # 입력 정규화 (공백/조사 처리)
│   │
│   ├── payment/                 # Sprint 4
│   │   ├── handler.go           # POST /payments/prepare, /confirm, /webhook
│   │   ├── service.go
│   │   ├── toss/
│   │   │   ├── client.go        # Toss API HTTP 클라이언트
│   │   │   └── webhook.go       # HMAC-SHA256 검증
│   │   ├── queries/
│   │   │   └── payments.sql
│   │   └── db/
│   │
│   ├── api/                     # 외부 API HTTP 클라이언트 (Go 측 — 즉시 응답용)
│   │   ├── kakao/
│   │   │   ├── client.go        # 베이스: retry, rate-limit, 캐시
│   │   │   └── geocode.go       # search_address, search_keyword
│   │   └── (Sprint 3 이후 추가)
│   │
│   ├── cache/
│   │   ├── redis.go             # go-redis 래퍼
│   │   └── keys.go              # 키 빌더 함수 (addr:resolve:..., rl:report:...)
│   │
│   ├── queue/
│   │   ├── stream.go            # Redis Streams XADD/XREADGROUP 헬퍼
│   │   └── contract.go          # Job 메시지 구조체 (Worker와 공유)
│   │
│   ├── storage/
│   │   ├── interface.go         # StorageClient 인터페이스
│   │   ├── minio.go             # MinIO 구현 (로컬)
│   │   └── presign.go           # presigned URL 생성
│   │
│   ├── middleware/
│   │   ├── auth.go              # RequireAuth, OptionalAuth
│   │   ├── ratelimit.go         # Redis sliding window
│   │   ├── logger.go            # slog request log + trace_id
│   │   ├── recovery.go          # panic → 500
│   │   ├── cors.go
│   │   └── request_id.go
│   │
│   ├── httperr/
│   │   └── error.go             # 표준 에러 응답 (code, message, detail)
│   │
│   └── server/
│       ├── server.go            # chi 라우터 + 미들웨어 체인
│       └── routes.go            # URL → handler 매핑
│
├── migrations/                  # golang-migrate
│   ├── 0001_sessions.up.sql
│   ├── 0001_sessions.down.sql
│   ├── 0002_users_auth_columns.up.sql
│   ├── 0002_users_auth_columns.down.sql
│   ├── 0003_reports_progress.up.sql
│   ├── ...
│
├── pkg/                         # 외부에서 import 가능 (현재 최소)
│   └── version/
│       └── version.go           # 빌드 시 -ldflags로 주입
│
├── python/                      # ★ Python 코드 내장 (Phase 4에서 복사)
│   ├── requirements.txt         # Python Worker 의존성
│   ├── api/                     # 외부 API 클라이언트 (카카오, 실거래가, 건축물대장, 토지이용규제)
│   │   ├── base.py, cache.py, rate_limiter.py
│   │   ├── clients/{kakao,real_transaction,building_register,land_use}.py
│   │   └── models/{address,transaction,building,land,location,news}.py
│   ├── generation/              # LLM 클라이언트 (CLI/API 듀얼 모드)
│   │   ├── llm_client.py        # create_llm_client(), CLILLMClient, APILLMClient
│   │   ├── graph.py, nodes.py, state.py
│   │   └── gen_prompts.py, conversation.py, citation_formatter.py, coreference.py
│   ├── query/                   # RAG 검색 파이프라인 (Phase 5-2 RAG 통합 시 사용)
│   │   ├── pipeline.py, analyzer.py, compensator.py, merger.py
│   │   └── config.py, prompts.py, alpha_trainer.py
│   ├── report/                  # 보고서 오케스트레이터 + 차트 + 프롬프트
│   │   ├── orchestrator.py      # ReportOrchestrator.generate() — Worker 진입점
│   │   ├── data_collector.py, address.py, charts.py, state.py, interview.py
│   │   ├── config/{__init__,params.yaml}
│   │   └── prompts/{price,location,legal,investment}.py
│   ├── rules/                   # 세금/대출 룰엔진
│   │   ├── engine.py            # run_all() — 취득세/양도세/보유세/대출
│   │   ├── loan.py, tax/{acquisition,transfer,holding}.py
│   │   └── tables/tax_rates_2026.yaml
│   └── worker/                  # Redis Streams 컨슈머 (Sprint 2에서 구현)
│       └── __init__.py
│
└── tests/
    ├── e2e/
    │   ├── auth_test.sh         # bash + curl
    │   └── reports_test.sh
    └── load/
        └── auth.js              # k6
```

> **Python 코드 내장 전략:** PYTHONPATH를 `python/`으로 설정하면 기존 import 경로
> (`from api.clients.kakao import KakaoMapClient` 등)가 **수정 없이** 그대로 동작한다.
> Config 파일(`params.yaml`, `tax_rates_2026.yaml`)은 `Path(__file__).resolve().parent` 패턴으로
> 로드되므로 파일 구조만 보존하면 경로가 자동으로 맞는다.

### 패키지 경계 원칙

- `internal/` 아래는 다른 모듈에서 import 불가 (Go 컴파일러가 강제)
- 도메인 패키지(`auth`, `user`, `report`, `payment`, `address`)는 서로를 직접 import하지 않는다 — 필요한 경우 `internal/server/`에서 DI로 주입
- `internal/api/`는 외부 HTTP 호출만, 비즈니스 로직 금지
- handler → service → db 단방향 호출, 역방향 금지

---

## 3. Python Worker (레포 내장)

Worker 코드는 `python/worker/` 에 위치하며, 같은 `python/` 안의 다른 모듈을 직접 import한다.

```
codes/realtor-ai-backend/python/worker/       # Sprint 2에서 구현
├── __init__.py
├── __main__.py                  # python -m worker
├── consumer.py                  # Redis Streams XREADGROUP 무한 루프
├── job.py                       # Job 메시지 → ReportOrchestrator 호출
├── progress.py                  # _notify(step, detail) → Redis PUBLISH
├── persistence.py               # Postgres UPDATE reports/report_sections
├── storage.py                   # MinIO 업로드 (Markdown, 차트 PNG)
├── config.py                    # 환경변수 로드 (DATABASE_URL, REDIS_URL 등)
└── tests/
    ├── test_progress_mapping.py
    └── test_consumer.py         # mock Redis로 단위 테스트
```

### Worker의 import 패턴

```python
# consumer.py 내부에서 — sys.path.insert 불필요 (PYTHONPATH=/app/python)
from report.orchestrator import ReportOrchestrator
from report.state import UserContext
from report.address import AddressNormalizer
from api.clients.kakao import KakaoMapClient
from api.clients.real_transaction import RealTransactionClient
from api.clients.building_register import BuildingRegisterClient
from generation.llm_client import create_llm_client
```

> Worker와 보고서 파이프라인 코드가 같은 레포(같은 `python/`)에 있으므로
> 수정 사항이 한 번의 커밋으로 반영되고, 클라우드 배포 시 단일 이미지로 빌드 가능하다.

---

## 4. 라이브러리 픽스 (Go)

`go.mod` 핵심 의존성:

```go
require (
    github.com/go-chi/chi/v5            v5.1.0
    github.com/go-chi/cors              v1.2.1
    github.com/jackc/pgx/v5             v5.6.0
    github.com/redis/go-redis/v9        v9.6.0
    github.com/lestrrat-go/jwx/v2       v2.1.1
    golang.org/x/crypto                 v0.27.0  // bcrypt
    github.com/golang-migrate/migrate/v4 v4.18.1
    github.com/minio/minio-go/v7        v7.0.77
    github.com/caarlos0/env/v11         v11.2.2
    github.com/go-playground/validator/v10 v10.22.1
    github.com/hashicorp/go-retryablehttp v0.7.7
    github.com/stretchr/testify         v1.9.0
)
```

> 버전은 구현 시점에 latest stable로 업데이트. 위는 2026-04 기준 안정 버전.

---

## 5. 빌드/실행 명령 (Makefile)

```makefile
.PHONY: dev build test lint migrate-up migrate-down sqlc clean

# 로컬 dev — air로 hot-reload (docker 컨테이너 안에서 자동 실행됨)
dev:
	air -c .air.toml

# 프로덕션 빌드
build:
	CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o ./bin/server ./cmd/server

# 테스트
test:
	go test -race -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out | tail -1

# 린트
lint:
	golangci-lint run ./...

# DB 마이그레이션
migrate-up:
	migrate -path ./migrations -database "$$DATABASE_URL" up

migrate-down:
	migrate -path ./migrations -database "$$DATABASE_URL" down 1

migrate-create:
	@read -p "마이그레이션 이름: " name; \
	migrate create -ext sql -dir ./migrations -seq $$name

# sqlc 코드 생성
sqlc:
	sqlc generate

# E2E 테스트
e2e:
	./tests/e2e/auth_test.sh
	./tests/e2e/reports_test.sh

clean:
	rm -rf ./bin ./tmp coverage.out
```

### .air.toml

```toml
root = "."
tmp_dir = "tmp"

[build]
  cmd = "go build -o ./tmp/server ./cmd/server"
  bin = "./tmp/server"
  delay = 500
  exclude_dir = ["tmp", "bin", "tests", "migrations"]
  include_ext = ["go"]
  stop_on_error = true

[log]
  time = true

[misc]
  clean_on_exit = true
```

---

## 6. 환경변수 (Go API)

`internal/config/config.go`의 구조체 (caarlos0/env 태그 사용):

```go
type Config struct {
    // 기본
    Env  string `env:"APP_ENV" envDefault:"local"`
    Port string `env:"PORT" envDefault:"8080"`

    // DB
    DatabaseURL string `env:"DATABASE_URL,required"`

    // Redis
    RedisURL string `env:"REDIS_URL,required"`

    // MinIO/Storage
    StorageEndpoint     string `env:"STORAGE_ENDPOINT,required"`
    StorageAccessKey    string `env:"STORAGE_ACCESS_KEY,required"`
    StorageSecretKey    string `env:"STORAGE_SECRET_KEY,required"`
    StorageBucketReports string `env:"STORAGE_BUCKET_REPORTS" envDefault:"realtor-reports"`

    // JWT
    JWTSecret        string        `env:"JWT_SECRET,required"`
    JWTRefreshSecret string        `env:"JWT_REFRESH_SECRET,required"`
    JWTAccessTTL     time.Duration `env:"JWT_ACCESS_TTL" envDefault:"15m"`
    JWTRefreshTTL    time.Duration `env:"JWT_REFRESH_TTL" envDefault:"168h"` // 7d

    // OAuth
    OAuthRedirectBaseURL string `env:"OAUTH_REDIRECT_BASE_URL" envDefault:"http://localhost:8080"`
    KakaoClientID       string `env:"KAKAO_CLIENT_ID"`
    KakaoClientSecret   string `env:"KAKAO_CLIENT_SECRET"`
    NaverClientID       string `env:"NAVER_CLIENT_ID"`
    NaverClientSecret   string `env:"NAVER_CLIENT_SECRET"`
    GoogleClientID      string `env:"GOOGLE_CLIENT_ID"`
    GoogleClientSecret  string `env:"GOOGLE_CLIENT_SECRET"`

    // Kakao (주소 정규화용 — OAuth와 다른 키)
    KakaoRestAPIKey string `env:"KAKAO_REST_API_KEY"`

    // Toss Payments (Sprint 4)
    TossTestMode    bool   `env:"TOSS_TEST_MODE" envDefault:"true"`
    TossClientKey   string `env:"TOSS_CLIENT_KEY"`
    TossSecretKey   string `env:"TOSS_SECRET_KEY"`

    // CORS
    CORSAllowOrigins []string `env:"CORS_ALLOW_ORIGINS" envDefault:"http://localhost:3000"`

    // Rate Limit
    RateLimitAuthPerMin   int `env:"RATELIMIT_AUTH_PER_MIN" envDefault:"60"`
    RateLimitReportPerMin int `env:"RATELIMIT_REPORT_PER_MIN" envDefault:"5"`
}
```

### `.env` 추가 항목 (기존 `.env.example` 위에 덧붙임)

```bash
# ── Go API 활성화 ─────────────────────────────────────────
GO_API_SRC_PATH=/home/gon/ws/rag/codes/realtor-ai-backend

# ── JWT (이미 JWT_SECRET 있음) ────────────────────────────
JWT_REFRESH_SECRET=local-dev-jwt-refresh-secret-change-in-production

# ── OAuth Client (Sprint 1) ──────────────────────────────
KAKAO_CLIENT_ID=
KAKAO_CLIENT_SECRET=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
OAUTH_REDIRECT_BASE_URL=http://localhost:8080

# ── Kakao 주소 API (Sprint 3) ────────────────────────────
KAKAO_REST_API_KEY=

# ── Toss Payments (Sprint 4) ─────────────────────────────
TOSS_TEST_MODE=true
TOSS_CLIENT_KEY=test_ck_xxxxxxxxxxxxxxxxxxxx
TOSS_SECRET_KEY=test_sk_xxxxxxxxxxxxxxxxxxxx
```

> OAuth 키는 카카오/네이버/Google Developer 콘솔에서 각각 발급. 로컬 개발용 redirect는
> `http://localhost:8080/api/v1/auth/oauth/{provider}/callback` 형식으로 등록.
> Sprint 1에서 키 발급 절차를 별도 가이드로 정리한다.

---

## 7. Sprint 0 — 레포 골격 작성 단계 (1일)

본 단계는 다른 모든 Sprint의 전제 조건이다.

### 7.1 작업 항목

1. `mkdir -p /home/gon/ws/rag/codes/realtor-ai-backend && cd $_`
2. `git init`
3. `.gitignore` 작성 (tmp/, bin/, .env, coverage.out)
4. `go mod init github.com/gon/realtor-ai-backend`
5. 위의 디렉토리 트리에서 **빈 go 파일들** 생성 (placeholder)
6. `cmd/server/main.go` — 헬스체크 1개만 있는 최소 서버
7. `Makefile`, `.air.toml`, `Dockerfile` 작성
8. 첫 마이그레이션 파일 `0001_sessions.up.sql` (다음 문서 참조)
9. `.env`에 `GO_API_SRC_PATH=/home/gon/ws/rag/codes/realtor-ai-backend` 추가
10. `cd codes/local-infra && docker compose up -d go-api`
11. `curl http://localhost:8080/health` → `{"status":"ok"}` 확인
12. `git add . && git commit -m "Sprint 0: 레포 골격 + 헬스체크"`

### 7.2 cmd/server/main.go 최소 골격 (Sprint 0)

```go
package main

import (
    "context"
    "log/slog"
    "net/http"
    "os"
    "os/signal"
    "syscall"
    "time"

    "github.com/go-chi/chi/v5"
)

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
    slog.SetDefault(logger)

    port := os.Getenv("PORT")
    if port == "" {
        port = "8080"
    }

    r := chi.NewRouter()
    r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.Write([]byte(`{"status":"ok"}`))
    })

    srv := &http.Server{
        Addr:         ":" + port,
        Handler:      r,
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 30 * time.Second,
    }

    go func() {
        slog.Info("server starting", "port", port)
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            slog.Error("server failed", "err", err)
            os.Exit(1)
        }
    }()

    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
    <-quit

    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    srv.Shutdown(ctx)
    slog.Info("server stopped")
}
```

### 7.3 Sprint 0 검증 체크리스트

- [ ] `docker compose ps`에서 `realtor-go-api`가 `Up` 상태
- [ ] `docker compose logs go-api`에 `air` 시작 로그 + Go 빌드 성공
- [ ] `curl http://localhost:8080/health` → `{"status":"ok"}`
- [ ] `cmd/server/main.go`의 한 줄 수정 후 저장 → air가 자동 재빌드 → 로그 갱신
- [ ] `git log`에 첫 커밋 존재
