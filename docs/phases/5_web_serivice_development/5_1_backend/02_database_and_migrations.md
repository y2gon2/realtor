# 02. 데이터베이스 스키마 + 마이그레이션 전략

> Phase 5-0의 [init.sql](../../../../codes/local-infra/postgres/init.sql)이 만들어 둔 5개 테이블을 시작점으로,
> Phase 5-1에서 필요한 컬럼/테이블을 `golang-migrate` SQL 마이그레이션으로 점진적으로 확장한다.

---

## 1. 기본 원칙

| 원칙 | 설명 |
|------|------|
| **init.sql은 그대로 둔다** | docker-compose가 최초 1회 자동 실행하는 1회성 부트스트랩으로 유지 |
| **추가 변경은 모두 migration** | `migrations/000{N}_{name}.up.sql` + `.down.sql` 쌍으로 관리 |
| **Sprint 단위로 마이그레이션 분할** | Sprint 1 = 0001~0002, Sprint 2 = 0003~0004, ... |
| **down 마이그레이션 필수** | 개발 중 롤백을 자주 하므로 모든 up은 down과 쌍으로 작성 |
| **idempotent 작성 권장** | `IF NOT EXISTS` / `IF EXISTS` 사용으로 재실행 안전성 확보 |
| **sqlc는 마이그레이션 후 schema 스냅샷을 본다** | sqlc.yaml에 schema 경로로 init.sql + migrations 모두 포함 |

---

## 2. 기존 init.sql 요약 (변경 금지)

[codes/local-infra/postgres/init.sql](../../../../codes/local-infra/postgres/init.sql)이 만드는 자산:

| 테이블 | 핵심 컬럼 |
|--------|---------|
| `users` | `id UUID PK`, `email UNIQUE`, `password_hash`, `auth_provider`, `provider_id`, `tier`, `created_at`, `updated_at` |
| `reports` | `id UUID PK`, `user_id FK`, `address_input`, `normalized_address JSONB`, `purpose`, `custom_notes`, `status`, `error_message`, `pdf_url`, `generation_time_ms`, `created_at`, `updated_at` |
| `report_sections` | `id UUID PK`, `report_id FK`, `section_type`, `content`, `chart_urls JSONB`, `generation_time_ms`, `created_at` |
| `payments` | `id UUID PK`, `user_id FK`, `pg_provider`, `pg_transaction_id`, `amount`, `currency`, `status`, `product_type`, `created_at`, `updated_at` |
| `api_cache` | `cache_key PK`, `response JSONB`, `api_source`, `expires_at`, `geom GEOMETRY(Point, 4326)`, `created_at` |

확장 모듈: `postgis`, `uuid-ossp`
인덱스: `idx_reports_user_id`, `idx_reports_status`, `idx_reports_created_at`, `idx_report_sections_report_id`, `idx_payments_user_id`, `idx_payments_status`, `idx_api_cache_expires`, `idx_api_cache_geom`(GIST)

---

## 3. Sprint별 마이그레이션 계획

### Sprint 1 — 인증

#### 0001_sessions.up.sql

```sql
-- Refresh token 세션 관리 테이블
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash VARCHAR(64) NOT NULL,  -- SHA-256 hex
    user_agent TEXT,
    ip_address INET,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_refresh_token_hash ON sessions(refresh_token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
```

#### 0001_sessions.down.sql

```sql
DROP TABLE IF EXISTS sessions;
```

#### 0002_users_auth_columns.up.sql

```sql
-- 인증 관련 컬럼 추가
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;

-- OAuth provider + provider_id 조합 unique
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_unique
    ON users(auth_provider, provider_id)
    WHERE auth_provider != 'email';
```

#### 0002_users_auth_columns.down.sql

```sql
DROP INDEX IF EXISTS idx_users_provider_unique;
ALTER TABLE users
    DROP COLUMN IF EXISTS locked_until,
    DROP COLUMN IF EXISTS failed_login_count,
    DROP COLUMN IF EXISTS last_login_at,
    DROP COLUMN IF EXISTS email_verified;
```

---

### Sprint 2 — 보고서 비동기 처리

#### 0003_reports_async.up.sql

```sql
-- 비동기 처리/진행률 추적용 컬럼
ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS job_id VARCHAR(64),         -- Redis Stream entry ID
    ADD COLUMN IF NOT EXISTS progress_percent SMALLINT NOT NULL DEFAULT 0
        CHECK (progress_percent >= 0 AND progress_percent <= 100),
    ADD COLUMN IF NOT EXISTS current_step VARCHAR(50),
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS markdown_url VARCHAR(2048); -- MinIO presigned URL용 키

-- 사용자별 최신 보고서 빠른 조회
CREATE INDEX IF NOT EXISTS idx_reports_user_created
    ON reports(user_id, created_at DESC);

-- 처리 중인 보고서 모니터링용
CREATE INDEX IF NOT EXISTS idx_reports_status_created
    ON reports(status, created_at)
    WHERE status IN ('pending', 'processing');
```

#### 0003_reports_async.down.sql

```sql
DROP INDEX IF EXISTS idx_reports_status_created;
DROP INDEX IF EXISTS idx_reports_user_created;
ALTER TABLE reports
    DROP COLUMN IF EXISTS markdown_url,
    DROP COLUMN IF EXISTS completed_at,
    DROP COLUMN IF EXISTS started_at,
    DROP COLUMN IF EXISTS current_step,
    DROP COLUMN IF EXISTS progress_percent,
    DROP COLUMN IF EXISTS job_id;
```

#### 0004_credits.up.sql

```sql
-- 사용자 크레딧 (Sprint 4 결제와 연결)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS credits_remaining INTEGER NOT NULL DEFAULT 2,
        -- 무료 가입 시 기본 2건
    ADD COLUMN IF NOT EXISTS credits_total_purchased INTEGER NOT NULL DEFAULT 0;

-- 크레딧 변동 이력 (감사용)
CREATE TABLE IF NOT EXISTS credit_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,  -- + = 충전, - = 사용
    reason VARCHAR(50) NOT NULL,  -- signup_bonus, payment, report_generation, refund
    related_payment_id UUID REFERENCES payments(id),
    related_report_id UUID REFERENCES reports(id),
    balance_after INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created
    ON credit_ledger(user_id, created_at DESC);
```

#### 0004_credits.down.sql

```sql
DROP TABLE IF EXISTS credit_ledger;
ALTER TABLE users
    DROP COLUMN IF EXISTS credits_total_purchased,
    DROP COLUMN IF EXISTS credits_remaining;
```

---

### Sprint 3 — 사용자/PIPA

#### 0005_users_pipa.up.sql

```sql
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS phone VARCHAR(20),
    ADD COLUMN IF NOT EXISTS marketing_consent BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS personal_data_consent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ;
        -- deletion_requested_at + 30일 = scheduled

-- 30일 grace period 후 삭제 잡 빠른 조회
CREATE INDEX IF NOT EXISTS idx_users_deletion_scheduled
    ON users(deletion_scheduled_at)
    WHERE deletion_scheduled_at IS NOT NULL;
```

#### 0006_pipa_audit_log.up.sql

```sql
-- PIPA 감사 로그 (열람권/삭제권 행사 기록)
CREATE TABLE IF NOT EXISTS pipa_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    user_email VARCHAR(255) NOT NULL,  -- user 삭제 후에도 보존
    action VARCHAR(50) NOT NULL,  -- consent, data_export, deletion_request, deletion_complete
    detail JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipa_audit_user_email_created
    ON pipa_audit_log(user_email, created_at DESC);
```

---

### Sprint 4 — 결제

#### 0007_payments_idempotency.up.sql

```sql
ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64),
    ADD COLUMN IF NOT EXISTS amount_currency VARCHAR(3) NOT NULL DEFAULT 'KRW',
    ADD COLUMN IF NOT EXISTS payment_method VARCHAR(20),  -- card, naverpay, kakaopay, tosspay
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS webhook_payload JSONB,
    ADD COLUMN IF NOT EXISTS receipt_url VARCHAR(2048);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_idempotency_unique
    ON payments(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_pg_transaction_unique
    ON payments(pg_provider, pg_transaction_id)
    WHERE pg_transaction_id IS NOT NULL;
```

---

## 4. sqlc 설정

### sqlc.yaml

```yaml
version: "2"
sql:
  - engine: "postgresql"
    queries:
      - "internal/auth/queries"
      - "internal/user/queries"
      - "internal/report/queries"
      - "internal/payment/queries"
    schema:
      - "../local-infra/postgres/init.sql"
      - "migrations"
    gen:
      go:
        package: "db"
        sql_package: "pgx/v5"
        out: "internal/sqlcgen"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        emit_db_tags: false
        rename:
          jsonb: "JSONB"
```

> **출력 위치 단일화:** sqlc는 모든 쿼리 파일을 하나로 묶어 `internal/sqlcgen/`에 생성한다.
> 각 도메인의 service.go에서 `import "github.com/gon/realtor-ai-backend/internal/sqlcgen"`로 사용.
> 도메인별 sqlc out으로 분리하지 않는 이유: cross-domain join 쿼리(예: reports + users)가 한 파일에 모일 수 있도록.

### 쿼리 작성 예시

`internal/auth/queries/users.sql`:

```sql
-- name: GetUserByEmail :one
SELECT * FROM users WHERE email = $1 LIMIT 1;

-- name: GetUserByID :one
SELECT * FROM users WHERE id = $1 LIMIT 1;

-- name: CreateUser :one
INSERT INTO users (
    email, name, password_hash, auth_provider, provider_id
) VALUES (
    $1, $2, $3, $4, $5
) RETURNING *;

-- name: UpdateUserLastLogin :exec
UPDATE users
SET last_login_at = NOW(), failed_login_count = 0, updated_at = NOW()
WHERE id = $1;

-- name: IncrementFailedLogin :exec
UPDATE users
SET failed_login_count = failed_login_count + 1,
    locked_until = CASE
        WHEN failed_login_count + 1 >= 5 THEN NOW() + INTERVAL '15 minutes'
        ELSE locked_until
    END,
    updated_at = NOW()
WHERE email = $1;
```

`internal/auth/queries/sessions.sql`:

```sql
-- name: CreateSession :one
INSERT INTO sessions (
    user_id, refresh_token_hash, user_agent, ip_address, expires_at
) VALUES (
    $1, $2, $3, $4, $5
) RETURNING *;

-- name: GetSessionByTokenHash :one
SELECT * FROM sessions
WHERE refresh_token_hash = $1
  AND revoked_at IS NULL
  AND expires_at > NOW()
LIMIT 1;

-- name: RevokeSession :exec
UPDATE sessions SET revoked_at = NOW() WHERE id = $1;

-- name: RevokeAllUserSessions :exec
UPDATE sessions SET revoked_at = NOW()
WHERE user_id = $1 AND revoked_at IS NULL;

-- name: DeleteExpiredSessions :execrows
DELETE FROM sessions WHERE expires_at < NOW();
```

---

## 5. 마이그레이션 운영

### 5.1 로컬 개발

`go-api` 컨테이너 안에서 실행:

```bash
# 컨테이너 진입
docker exec -it realtor-go-api bash

# 마이그레이션 도구 설치 (1회)
go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

# 적용
make migrate-up

# 롤백 1단계
make migrate-down

# 새 마이그레이션 생성
make migrate-create
# → 이름 입력 → migrations/000N_name.up.sql + .down.sql 생성
```

### 5.2 강제 리셋 (개발 중 스키마 충돌 시)

```bash
# 1. docker compose down
cd /home/gon/ws/rag/codes/local-infra
docker compose down

# 2. pgdata 볼륨 삭제 (모든 데이터 사라짐)
docker volume rm realtor-pgdata

# 3. 재시작 → init.sql 다시 실행
docker compose up -d postgres

# 4. 마이그레이션 처음부터 적용
docker exec -it realtor-go-api make migrate-up
```

### 5.3 프로덕션 (Phase 5-2)

K8s Job으로 배포 직전 1회 실행:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate-${BUILD_ID}
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: gcr.io/realtor-ai-prod/realtor-ai-backend:${TAG}
          command: ["./migrate"]
          args: ["-path", "/migrations", "-database", "$(DATABASE_URL)", "up"]
          envFrom:
            - secretRef:
                name: db-credentials
      restartPolicy: Never
```

---

## 6. 마이그레이션 순서 요약

| # | 파일 | Sprint | 영향 |
|---|------|--------|------|
| 0001 | sessions | 1 | 신규 테이블 |
| 0002 | users_auth_columns | 1 | users 컬럼 추가 |
| 0003 | reports_async | 2 | reports 컬럼 추가 + 인덱스 |
| 0004 | credits | 2 | users 컬럼 + credit_ledger 신규 |
| 0005 | users_pipa | 3 | users 컬럼 추가 |
| 0006 | pipa_audit_log | 3 | 신규 테이블 |
| 0007 | payments_idempotency | 4 | payments 컬럼 추가 + unique 인덱스 |

총 7개의 .up/.down 쌍. 각 Sprint 시작 시 해당 마이그레이션을 작성·적용한 후 sqlc 쿼리 작성으로 진행.

---

## 7. 검증

### 7.1 마이그레이션 자체 검증

- [ ] `make migrate-up` → 모든 마이그레이션이 에러 없이 적용
- [ ] `make migrate-down` 7회 → 모든 변경 사항이 roll back
- [ ] `make migrate-up` 다시 → 정상 재적용 (idempotent)
- [ ] `psql ... -c "\dt"` → 신규 테이블 존재 확인 (sessions, credit_ledger, pipa_audit_log)
- [ ] `psql ... -c "\d users"` → 추가 컬럼 모두 존재

### 7.2 sqlc 코드 생성 검증

- [ ] `make sqlc` → 에러 없음
- [ ] `internal/sqlcgen/` 아래에 Go 파일들 생성됨
- [ ] `go build ./...` → 컴파일 성공
