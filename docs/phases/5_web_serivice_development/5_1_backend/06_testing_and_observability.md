# 06. 테스트 + 관측 (Observability) 전략

> 모든 Sprint에 공통으로 적용되는 테스트 계층, 로깅, 메트릭, 트레이싱 전략.
> Phase 5-2(GCP 마이그레이션) 전환 시 관측 도구만 교체하면 되도록 설계.

---

## 1. 테스트 계층

```
       ┌─────────────────────────────────────┐
       │  E2E (bash + curl + k6)             │  Sprint 종료 시 1회
       │  - tests/e2e/*.sh                    │  - 사용자 시나리오 통째로
       └─────────────────────────────────────┘
              ▲
              │
       ┌─────────────────────────────────────┐
       │  Integration (Go + 실제 인프라)        │  매 PR
       │  - //go:build integration            │  - DB/Redis/MinIO 실제 사용
       └─────────────────────────────────────┘
              ▲
              │
       ┌─────────────────────────────────────┐
       │  Unit (Go _test.go + httptest)      │  매 커밋
       │  - 빠름, 외부 의존 mock              │  - 커버리지 60%+ 목표
       └─────────────────────────────────────┘
```

---

## 2. 단위 테스트 (Unit)

### 2.1 도구

- 표준 `testing` + `stretchr/testify/assert`, `require`
- mock: 표준 `interface` + 직접 구현 (gomock 미사용 — 단순함)
- HTTP: `net/http/httptest`

### 2.2 패키지별 목표

| 패키지 | 핵심 테스트 | 목표 커버리지 |
|--------|----------|--------------|
| `internal/auth` | password/jwt round-trip, signup/login 분기, 계정 잠금 | 80%+ |
| `internal/auth/oauth` | 각 provider mock 서버로 Exchange/FetchProfile | 70%+ |
| `internal/report` | 크레딧 차감 트랜잭션, SSE 변환 | 70%+ |
| `internal/queue` | XADD/XREADGROUP wrapper | 60%+ |
| `internal/middleware` | RequireAuth/RateLimit 분기 | 80%+ |
| `internal/payment/toss` | stub mode 응답, HMAC 검증 | 80%+ |
| `internal/api/kakao` | 캐시 히트/미스, retry 로직 | 70%+ |

전체 목표: **`make test` 실행 시 60%+**

### 2.3 예시: handler 테스트

```go
func TestSignupHandler_Success(t *testing.T) {
    db := newMockDB(t)
    rdb := newMockRedis(t)
    svc := auth.NewService(db, rdb, testTokenManager())
    h := auth.NewHandler(svc)

    body := strings.NewReader(`{"email":"a@b.com","password":"Strong1234","name":"테스트"}`)
    req := httptest.NewRequest("POST", "/api/v1/auth/signup", body)
    req.Header.Set("Content-Type", "application/json")
    rec := httptest.NewRecorder()

    h.Signup(rec, req)

    require.Equal(t, 201, rec.Code)
    var resp auth.SignupResponse
    require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
    assert.NotEmpty(t, resp.AccessToken)
    assert.Equal(t, "a@b.com", resp.User.Email)
}
```

---

## 3. 통합 테스트 (Integration)

### 3.1 도구

- 빌드 태그 `//go:build integration`로 분리
- `make test-integration` → `go test -tags=integration ./...`
- **실제** PostgreSQL/Redis/MinIO 사용 (docker compose 띄운 상태)
- 매 테스트 시작 시 fixture로 DB 초기화 (`TRUNCATE` cascade)

### 3.2 패턴

```go
//go:build integration

package report_test

func TestReportPipeline_E2E(t *testing.T) {
    if testing.Short() {
        t.Skip("integration test")
    }
    // 실제 connection
    db := openTestDB(t)
    rdb := openTestRedis(t)
    minio := openTestMinIO(t)
    defer cleanupAll(t, db, rdb, minio)

    // 1. 사용자 가입 (직접 INSERT)
    user := createTestUser(t, db)

    // 2. 보고서 생성 요청
    payload := report.CreateRequest{...}
    reportID := svc.Create(ctx, user.ID, payload)

    // 3. Worker가 처리할 때까지 polling (또는 mock Worker)
    waitForStatus(t, db, reportID, "completed", 60*time.Second)

    // 4. 검증
    r := svc.Get(ctx, reportID)
    require.Equal(t, "completed", r.Status)
    require.NotEmpty(t, r.Sections)
}
```

### 3.3 Worker mock vs 실제 Worker

- **빠른 통합 테스트:** Worker 없이 별도 goroutine에서 mock orchestrator 호출 → 진행률 PUBLISH
- **느린 E2E 테스트:** 실제 Python Worker 컨테이너 동작 + Phase 4 코드 호출 (golden 주소 사용)

---

## 4. E2E 테스트 (bash + curl)

### 4.1 위치

```
codes/realtor-ai-backend/tests/e2e/
├── _common.sh           # BASE_URL, helper 함수
├── auth_test.sh         # Sprint 1
├── reports_test.sh      # Sprint 2
├── address_test.sh      # Sprint 3
├── user_pipa_test.sh    # Sprint 3
├── payment_test.sh      # Sprint 4
└── full_flow.sh         # 5-1 전체 시나리오
```

### 4.2 _common.sh

```bash
#!/bin/bash
BASE_URL="${BASE_URL:-http://localhost:8080/api/v1}"
TIMESTAMP=$(date +%s)
TEST_EMAIL="e2e-test-$TIMESTAMP@example.com"
TEST_PASSWORD="Strong1234"

assert_eq() {
    local expected="$1" actual="$2" msg="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $msg — expected '$expected', got '$actual'"
        exit 1
    fi
}

curl_json() {
    curl -sf -H 'Content-Type: application/json' "$@"
}
```

### 4.3 실행

```bash
# 모든 E2E
make e2e

# 특정 Sprint
./tests/e2e/auth_test.sh
./tests/e2e/reports_test.sh
```

### 4.4 CI 통합 (선택, Phase 5-2에서 GitHub Actions로)

```yaml
- name: Start infra
  run: cd codes/local-infra && docker compose up -d postgres redis minio go-api python-worker

- name: Wait for healthy
  run: ./scripts/wait-for-healthy.sh

- name: Run E2E
  run: cd codes/realtor-ai-backend && make e2e
```

---

## 5. 부하 테스트 (k6)

### 5.1 도구

- [Grafana k6](https://k6.io/) — JavaScript 시나리오, CLI 단일 바이너리
- `tests/load/` 디렉토리에 시나리오 파일

### 5.2 시나리오

| 파일 | 대상 | 목표 |
|------|------|------|
| `tests/load/auth.js` | `POST /auth/login` | 50 VU, p95 < 200ms |
| `tests/load/reports.js` | `POST /reports` | 10 VU, 5/min rate limit 동작 검증 |
| `tests/load/sse.js` | SSE 동시 100 연결 | 메모리 안정성 |

### 5.3 예시: auth.js

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 },
    { duration: '1m',  target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const payload = JSON.stringify({
    email: `loadtest-${__VU}@example.com`,
    password: 'Strong1234',
  });
  const res = http.post('http://localhost:8080/api/v1/auth/login', payload, {
    headers: { 'Content-Type': 'application/json' },
  });
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
```

---

## 6. 로깅 (slog)

### 6.1 설정

`cmd/server/main.go`:

```go
logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
    Level: slog.LevelInfo,
    AddSource: false,
    ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
        if a.Key == slog.TimeKey {
            return slog.Attr{Key: "ts", Value: slog.StringValue(a.Value.Time().UTC().Format(time.RFC3339Nano))}
        }
        if a.Key == slog.LevelKey {
            return slog.Attr{Key: "level", Value: slog.StringValue(strings.ToLower(a.Value.String()))}
        }
        return a
    },
}))
slog.SetDefault(logger)
```

### 6.2 Request ID 미들웨어

`internal/middleware/request_id.go`:

```go
type ctxKey int
const requestIDKey ctxKey = iota

func RequestID(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        rid := r.Header.Get("X-Request-ID")
        if rid == "" {
            rid = uuid.New().String()
        }
        w.Header().Set("X-Request-ID", rid)
        ctx := context.WithValue(r.Context(), requestIDKey, rid)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}

func RequestIDFromContext(ctx context.Context) string {
    if v, ok := ctx.Value(requestIDKey).(string); ok {
        return v
    }
    return ""
}
```

### 6.3 로그 미들웨어

```go
func Logger(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
        next.ServeHTTP(ww, r)

        slog.InfoContext(r.Context(), "http request",
            "request_id", RequestIDFromContext(r.Context()),
            "method", r.Method,
            "path", r.URL.Path,
            "status", ww.Status(),
            "size", ww.BytesWritten(),
            "duration_ms", time.Since(start).Milliseconds(),
            "user_agent", r.Header.Get("User-Agent"),
            "ip", clientIP(r),
        )
    })
}
```

### 6.4 출력 예시

```json
{"ts":"2026-04-08T10:00:00.123Z","level":"info","msg":"http request","request_id":"abc-123","method":"POST","path":"/api/v1/reports","status":202,"size":123,"duration_ms":15,"user_agent":"...","ip":"172.18.0.1"}
```

### 6.5 Python Worker 로깅

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
            **(record.extra if hasattr(record, "extra") else {}),
        })

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(handler)
```

### 6.6 도커 로그 확인

```bash
docker compose logs -f go-api python-worker | jq -c .
```

---

## 7. 메트릭 (Prometheus)

### 7.1 노출 엔드포인트

`/metrics` — 인증 없음, 내부망 한정 (Phase 5-2 GCP에서 NetworkPolicy로 차단)

### 7.2 라이브러리

- `github.com/prometheus/client_golang/prometheus`
- `github.com/prometheus/client_golang/prometheus/promhttp`

### 7.3 핵심 메트릭

| 이름 | 타입 | 라벨 | 의미 |
|------|------|------|------|
| `realtor_http_requests_total` | Counter | method, path, status | 요청 카운트 |
| `realtor_http_request_duration_seconds` | Histogram | method, path | 응답 시간 분포 |
| `realtor_auth_login_total` | Counter | result(success/fail) | 로그인 시도 |
| `realtor_reports_created_total` | Counter | purpose | 보고서 생성 요청 |
| `realtor_reports_completed_total` | Counter | status(completed/failed) | 보고서 종료 |
| `realtor_reports_in_progress` | Gauge | - | 처리 중 보고서 수 |
| `realtor_queue_depth` | Gauge | stream | 대기 메시지 수 (XLEN) |
| `realtor_redis_op_duration_seconds` | Histogram | op | Redis 호출 시간 |
| `realtor_db_query_duration_seconds` | Histogram | query | DB 쿼리 시간 |

### 7.4 큐 깊이 측정 (별도 goroutine)

```go
func startQueueMetricsExporter(rdb *redis.Client, gauge prometheus.Gauge) {
    go func() {
        ticker := time.NewTicker(15 * time.Second)
        for range ticker.C {
            ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
            n, err := rdb.XLen(ctx, "realtor:reports").Result()
            cancel()
            if err == nil {
                gauge.Set(float64(n))
            }
        }
    }()
}
```

### 7.5 로컬 확인

```bash
curl http://localhost:8080/metrics | grep realtor_
```

> Phase 5-2에서 GMP(Google Managed Prometheus)로 자동 수집.

---

## 8. 트레이싱 (OpenTelemetry)

### 8.1 라이브러리

- `go.opentelemetry.io/otel`
- `go.opentelemetry.io/otel/sdk`
- `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`
- `go.opentelemetry.io/otel/exporters/stdout/stdouttrace` (로컬)

### 8.2 설정 (로컬)

```go
exporter, _ := stdouttrace.New(stdouttrace.WithPrettyPrint())
tp := sdktrace.NewTracerProvider(
    sdktrace.WithBatcher(exporter),
    sdktrace.WithResource(resource.NewWithAttributes(
        semconv.SchemaURL,
        semconv.ServiceNameKey.String("realtor-go-api"),
        semconv.DeploymentEnvironmentKey.String(cfg.Env),
    )),
)
otel.SetTracerProvider(tp)
```

### 8.3 자동 계측

- HTTP 라우터: `r.Use(otelhttp.NewMiddleware("realtor-go-api"))`
- DB: `pgx`는 OpenTelemetry contrib 패키지 사용
- Redis: `go-redis`도 contrib 존재

### 8.4 수동 span

```go
func (s *Service) Create(ctx context.Context, req CreateRequest) (uuid.UUID, error) {
    ctx, span := tracer.Start(ctx, "report.Service.Create")
    defer span.End()

    span.SetAttributes(
        attribute.String("user.id", req.UserID.String()),
        attribute.String("purpose", req.Purpose),
    )

    // ... 비즈니스 로직
}
```

### 8.5 Phase 5-2 전환

`stdouttrace` → `cloudtrace` exporter 1줄 교체로 GCP Cloud Trace로 전환.

---

## 9. CI/CD에서의 검증 (Phase 5-2 준비)

본 문서는 Phase 5-1 범위지만, CI 파이프라인 구조는 Sprint 4 마무리 시 GitHub Actions yml 초안을 작성해 둔다.

```yaml
name: backend-ci
on: [pull_request]

jobs:
  lint-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.24' }
      - run: cd codes/realtor-ai-backend && make lint
      - run: cd codes/realtor-ai-backend && make test

  integration:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgis/postgis:15-3.4, env: { ... }, ports: ['5432:5432'] }
      redis:    { image: redis:7.2-alpine, ports: ['6379:6379'] }
      minio:    { image: minio/minio:latest, ports: ['9000:9000'] }
    steps:
      - uses: actions/checkout@v4
      - run: ./scripts/wait-for-healthy.sh
      - run: cd codes/realtor-ai-backend && make migrate-up && make test-integration
```

---

## 10. 검증 체크리스트 (Observability 자체)

- [ ] 모든 HTTP 요청 로그가 JSON 형식 + request_id 포함
- [ ] `curl http://localhost:8080/metrics` → Prometheus 형식 응답
- [ ] `realtor_http_requests_total` 카운터가 요청마다 증가
- [ ] `realtor_queue_depth` 게이지가 보고서 생성 시 상승, 완료 시 하락
- [ ] OpenTelemetry stdout exporter가 trace 출력
- [ ] Python Worker 로그도 JSON 형식
- [ ] `make test` → unit test 60%+ 커버리지
- [ ] `make test-integration` → 실제 인프라로 통과
- [ ] `make e2e` → 모든 sprint 시나리오 통과
- [ ] `tests/load/auth.js` k6 시나리오 → p95 < 200ms

---

## 11. 5-1 종료 시 산출 정리

본 단계 종료 시 다음이 정리되어 있어야 한다:

1. **코드:**
   - `codes/realtor-ai-backend/` (Go API, 7개 마이그레이션, 단위/통합/E2E 테스트)
   - `codes/realtor-ai-worker/` (Python Worker)
2. **문서:**
   - `planning/docs/phases/5_web_serivice_development/5_1_backend/00~06.md` (본 7개)
   - `codes/realtor-ai-backend/README.md` (개발자 빠른 시작)
   - `codes/realtor-ai-backend/docs/oauth_setup.md` (3사 OAuth 키 발급 가이드)
3. **검증 결과:**
   - `tests/e2e/full_flow.sh` 실행 로그 (성공)
   - `make test` 커버리지 리포트
   - k6 부하 테스트 리포트
4. **다음 Phase 인계:**
   - Phase 5-2 (GCP 배포)에서 변경되어야 할 항목 리스트
   - Phase 5-3 (Frontend)에서 사용할 OpenAPI 스펙 (5-1 마지막에 생성)
