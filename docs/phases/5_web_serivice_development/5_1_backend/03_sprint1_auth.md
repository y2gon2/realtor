# 03. Sprint 1 — 인증 시스템 (JWT + 소셜 로그인)

> **목표:** 사용자가 이메일/비밀번호 또는 카카오/네이버/Google OAuth로 가입·로그인하여 JWT를 받고,
> 이후 모든 보호된 엔드포인트가 이 토큰으로 인증되도록 한다.
>
> **선행 조건:** Sprint 0(레포 골격) 완료, 마이그레이션 0001/0002 적용 완료

---

## 1. 산출물

- `internal/auth/` 패키지 (handler, service, jwt, password, oauth/)
- 9개 HTTP 엔드포인트
- `RequireAuth`, `RateLimit` 미들웨어
- 단위 테스트 + E2E curl 시나리오
- OAuth 키 발급 가이드 (별도 README)

---

## 2. 도메인 모델

`internal/auth/models.go`:

```go
type User struct {
    ID                 uuid.UUID
    Email              string
    Name               string
    PasswordHash       *string  // nil for OAuth users
    AuthProvider       string   // "email", "kakao", "naver", "google"
    ProviderID         *string  // nil for email users
    Tier               string   // "free", "basic", "pro"
    EmailVerified      bool
    LastLoginAt        *time.Time
    FailedLoginCount   int
    LockedUntil        *time.Time
    CreditsRemaining   int
    CreatedAt          time.Time
    UpdatedAt          time.Time
}

type Session struct {
    ID                uuid.UUID
    UserID            uuid.UUID
    RefreshTokenHash  string  // SHA-256 hex
    UserAgent         *string
    IPAddress         *netip.Addr
    ExpiresAt         time.Time
    CreatedAt         time.Time
    LastUsedAt        time.Time
    RevokedAt         *time.Time
}

type OAuthProfile struct {
    Provider    string  // "kakao" | "naver" | "google"
    ProviderID  string
    Email       string
    Name        string
}
```

---

## 3. JWT 전략

### 3.1 토큰 종류

| 종류 | 알고리즘 | TTL | 저장 위치 | 페이로드 |
|------|---------|-----|----------|---------|
| Access | HS256 | 15분 | 클라이언트 메모리 (Authorization 헤더) | `sub`, `email`, `tier`, `iat`, `exp` |
| Refresh | HS256 | 7일 | DB sessions 테이블 + 클라이언트 (httpOnly Secure cookie 또는 응답 body) | `sub`, `jti`, `iat`, `exp` |

### 3.2 발급/검증

`internal/auth/jwt.go`:

```go
type TokenManager struct {
    accessSecret  []byte
    refreshSecret []byte
    accessTTL     time.Duration
    refreshTTL    time.Duration
}

type Claims struct {
    UserID uuid.UUID `json:"sub"`
    Email  string    `json:"email,omitempty"`
    Tier   string    `json:"tier,omitempty"`
    JTI    string    `json:"jti,omitempty"`
}

func (tm *TokenManager) IssueAccessToken(user *User) (string, error)
func (tm *TokenManager) IssueRefreshToken(userID uuid.UUID) (token string, jti string, err error)
func (tm *TokenManager) ParseAccessToken(token string) (*Claims, error)
func (tm *TokenManager) ParseRefreshToken(token string) (*Claims, error)
```

- `lestrrat-go/jwx/v2/jwt` 사용
- Refresh token의 raw 값은 클라이언트에만 전달, 서버는 SHA-256 해시만 sessions 테이블에 저장
- 토큰 회전(rotation): refresh 사용 시 기존 세션 revoke + 신규 세션 발급

### 3.3 비밀번호 해시

`internal/auth/password.go`:

```go
const bcryptCost = 12

func HashPassword(plain string) (string, error)
func VerifyPassword(plain, hash string) error
```

- `golang.org/x/crypto/bcrypt`
- 최소 길이 8자, 알파벳+숫자 조합 필수 (validator 태그)

### 3.4 계정 잠금 정책

| 조건 | 동작 |
|------|------|
| 연속 5회 로그인 실패 | 15분 잠금 (`locked_until` 설정) |
| 잠금 중 로그인 시도 | 401 + `account_locked` 코드 |
| 성공 로그인 | `failed_login_count` 0으로 리셋 |

---

## 4. OAuth 통합

### 4.1 OAuthProvider 인터페이스

`internal/auth/oauth/provider.go`:

```go
type Provider interface {
    Name() string                              // "kakao", "naver", "google"
    AuthorizeURL(state, redirectURI string) string
    Exchange(ctx context.Context, code, redirectURI string) (*Token, error)
    FetchProfile(ctx context.Context, token *Token) (*OAuthProfile, error)
}

type Token struct {
    AccessToken  string
    RefreshToken string
    ExpiresIn    int
    TokenType    string
}
```

### 4.2 카카오 구현 (`oauth/kakao.go`)

| 단계 | URL | 비고 |
|------|-----|------|
| Authorize | `https://kauth.kakao.com/oauth/authorize` | client_id, redirect_uri, response_type=code, state |
| Token | `https://kauth.kakao.com/oauth/token` | grant_type=authorization_code |
| Profile | `https://kapi.kakao.com/v2/user/me` | Authorization: Bearer {access_token} |

응답 매핑: `id` → `provider_id`, `kakao_account.email` → `email`, `properties.nickname` → `name`

### 4.3 네이버 구현 (`oauth/naver.go`)

| 단계 | URL |
|------|-----|
| Authorize | `https://nid.naver.com/oauth2.0/authorize` |
| Token | `https://nid.naver.com/oauth2.0/token` |
| Profile | `https://openapi.naver.com/v1/nid/me` |

응답 매핑: `response.id` → `provider_id`, `response.email` → `email`, `response.name` → `name`

### 4.4 Google 구현 (`oauth/google.go`)

| 단계 | URL |
|------|-----|
| Authorize | `https://accounts.google.com/o/oauth2/v2/auth` |
| Token | `https://oauth2.googleapis.com/token` |
| Profile | `https://www.googleapis.com/oauth2/v3/userinfo` |

scope: `openid email profile`
응답 매핑: `sub` → `provider_id`, `email` → `email`, `name` → `name`

### 4.5 State 파라미터 (CSRF 방어)

- `crypto/rand`로 32바이트 생성 → base64 url-safe
- Redis에 `oauth:state:{state}` = `{provider, ip}` (TTL 5분) 저장
- 콜백 시 일치하지 않으면 400

### 4.6 OAuth 가입/로그인 분기

콜백에서 `(provider, provider_id)` 조합으로 users 검색:

| 결과 | 동작 |
|------|------|
| 존재 | 로그인 → 토큰 발급 |
| 미존재 + 같은 email로 다른 provider 가입 | 409 `email_already_exists_with_different_provider` (Phase 5-2에서 계정 통합 UI 추가) |
| 미존재 + 신규 email | INSERT users + 가입 보너스 크레딧 2건 + 토큰 발급 |

---

## 5. 미들웨어

### 5.1 RequireAuth (`middleware/auth.go`)

```go
func RequireAuth(tm *auth.TokenManager) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            h := r.Header.Get("Authorization")
            if !strings.HasPrefix(h, "Bearer ") {
                httperr.Write(w, 401, "missing_token", "Authorization header required")
                return
            }
            token := strings.TrimPrefix(h, "Bearer ")
            claims, err := tm.ParseAccessToken(token)
            if err != nil {
                httperr.Write(w, 401, "invalid_token", err.Error())
                return
            }
            ctx := context.WithValue(r.Context(), authCtxKey, claims)
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}

func ClaimsFromContext(ctx context.Context) (*auth.Claims, bool)
```

### 5.2 RateLimit (`middleware/ratelimit.go`)

Redis sliding window:

```go
func RateLimit(rdb *redis.Client, keyFn func(*http.Request) string, limit int, window time.Duration) func(http.Handler) http.Handler
```

- 키 빌더 예: `func(r) string { return "rl:auth:" + clientIP(r) }`
- Redis Lua 스크립트로 INCR + EXPIRE atomic
- 초과 시 429 + `Retry-After` 헤더

| 라우트 | 키 | 제한 |
|--------|----|------|
| `/auth/signup`, `/auth/login` | IP | 60/min |
| `/auth/oauth/*/callback` | IP | 30/min |
| `/auth/refresh` | user_id | 30/min |

---

## 6. 엔드포인트 명세

### 6.1 `POST /api/v1/auth/signup`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "Strong1234",
  "name": "홍길동",
  "marketing_consent": false
}
```

**Validation:**
- email: format, max 255
- password: min 8, alphanumeric mix
- name: max 100

**Response 201:**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "홍길동",
    "tier": "free",
    "credits_remaining": 2,
    "created_at": "2026-04-08T10:00:00Z"
  },
  "access_token": "eyJhbGciOiJIUzI1...",
  "refresh_token": "eyJhbGciOiJIUzI1..."
}
```

**Errors:**
- 400 `invalid_email`, `weak_password`
- 409 `email_already_exists`

---

### 6.2 `POST /api/v1/auth/login`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "Strong1234"
}
```

**Response 200:** signup과 동일 구조

**Errors:**
- 401 `invalid_credentials`
- 401 `account_locked` (with `locked_until`)

---

### 6.3 `GET /api/v1/auth/oauth/{provider}/authorize`

`provider` ∈ `{kakao, naver, google}`

**Response 302:**
```
Location: https://kauth.kakao.com/oauth/authorize?client_id=...&redirect_uri=...&state=...&response_type=code
```

쿼리 파라미터: `?return_to=/dashboard` (옵션, 콜백 후 프론트엔드 리다이렉트용)
state Redis에 `return_to` 함께 저장.

---

### 6.4 `GET /api/v1/auth/oauth/{provider}/callback`

OAuth provider가 호출하는 콜백.

**Query:** `?code=...&state=...`

**처리:**
1. state 검증 (Redis에서 조회·삭제)
2. `provider.Exchange(code)` → access token
3. `provider.FetchProfile(token)` → email, provider_id
4. 사용자 조회 또는 신규 생성
5. JWT Access + Refresh 발급
6. 프론트엔드로 302 (토큰을 fragment 또는 cookie로 전달)

**프론트엔드 전달 방식 (로컬 개발):**
```
Location: http://localhost:3000/auth/callback#access_token=...&refresh_token=...&return_to=/dashboard
```

> 프로덕션에서는 httpOnly Secure cookie 사용. 5-2에서 전환.

---

### 6.5 `POST /api/v1/auth/refresh`

**Request:**
```json
{ "refresh_token": "eyJ..." }
```

**처리:**
1. 토큰 파싱 → 유효성 검증
2. SHA-256 해시 → sessions 테이블 조회
3. 유효 세션이면: 기존 revoke + 신규 access/refresh 발급 + 신규 session INSERT
4. 무효이면: 401 + 사용자의 모든 세션 revoke (탈취 의심)

**Response 200:**
```json
{
  "access_token": "...",
  "refresh_token": "..."
}
```

---

### 6.6 `POST /api/v1/auth/logout`

**Request:** (인증 필요)
```json
{ "refresh_token": "eyJ..." }
```

**처리:** 해당 세션 + access token (선택적으로 redis blocklist) revoke

**Response 204**

---

### 6.7 `POST /api/v1/auth/logout-all`

**Request:** (인증 필요, body 없음)

**처리:** 사용자의 모든 세션 revoke

**Response 204**

---

### 6.8 `GET /api/v1/auth/me`

**Header:** `Authorization: Bearer <access>`

**Response 200:**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "홍길동",
    "tier": "free",
    "credits_remaining": 2,
    "auth_provider": "kakao",
    "email_verified": true,
    "last_login_at": "2026-04-08T10:00:00Z"
  }
}
```

---

### 6.9 `POST /api/v1/auth/change-password`

**인증 필요. email 가입 사용자만.**

**Request:**
```json
{
  "current_password": "...",
  "new_password": "..."
}
```

**처리:** 현재 비밀번호 검증 → bcrypt 새로 해시 → UPDATE → 모든 세션 revoke

**Response 204**

**Errors:**
- 400 `oauth_user` (OAuth 가입자는 비밀번호 없음)
- 401 `invalid_password`

---

## 7. 라우터 등록

`internal/server/routes.go`:

```go
func RegisterAuthRoutes(r chi.Router, h *auth.Handler, mw *middleware.Stack) {
    r.Route("/api/v1/auth", func(r chi.Router) {
        r.Group(func(r chi.Router) {
            r.Use(mw.RateLimitByIP(60))
            r.Post("/signup", h.Signup)
            r.Post("/login", h.Login)
            r.Post("/refresh", h.Refresh)
        })

        r.Group(func(r chi.Router) {
            r.Use(mw.RateLimitByIP(30))
            r.Get("/oauth/{provider}/authorize", h.OAuthAuthorize)
            r.Get("/oauth/{provider}/callback", h.OAuthCallback)
        })

        r.Group(func(r chi.Router) {
            r.Use(mw.RequireAuth)
            r.Get("/me", h.Me)
            r.Post("/logout", h.Logout)
            r.Post("/logout-all", h.LogoutAll)
            r.Post("/change-password", h.ChangePassword)
        })
    })
}
```

---

## 8. 환경변수 (Sprint 1 신규/필수)

| 변수 | 필수 | 예시 | 비고 |
|------|------|------|------|
| `JWT_SECRET` | ✅ | random 32-char | 이미 .env에 있음 |
| `JWT_REFRESH_SECRET` | ✅ | random 32-char | Sprint 1에서 추가 |
| `JWT_ACCESS_TTL` | ❌ | `15m` | 기본 15분 |
| `JWT_REFRESH_TTL` | ❌ | `168h` | 기본 7일 |
| `KAKAO_CLIENT_ID` | OAuth 사용 시 | | Kakao Developer 콘솔 |
| `KAKAO_CLIENT_SECRET` | OAuth 사용 시 | | |
| `NAVER_CLIENT_ID` | OAuth 사용 시 | | Naver Developer 콘솔 |
| `NAVER_CLIENT_SECRET` | OAuth 사용 시 | | |
| `GOOGLE_CLIENT_ID` | OAuth 사용 시 | | Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth 사용 시 | | |
| `OAUTH_REDIRECT_BASE_URL` | OAuth 사용 시 | `http://localhost:8080` | 콜백 URL prefix |

> 로컬 개발 초기에는 OAuth 키 없이 이메일/비밀번호 가입만으로도 Sprint 1 통과 가능.
> OAuth 키는 기능 검증 단계에서 발급. 키 발급 가이드는 별도 README로 작성.

---

## 9. 테스트 전략

### 9.1 단위 테스트 (`*_test.go`)

| 대상 | 테스트 |
|------|--------|
| `password.go` | bcrypt 해시/검증 round-trip |
| `jwt.go` | 발급→파싱 round-trip, 만료 검증, 잘못된 secret 거부 |
| `oauth/kakao.go` | httptest mock 서버로 Exchange/FetchProfile 검증 |
| `service.go` | mock DB로 비즈니스 로직 (계정 잠금, 가입 분기) 검증 |
| `handler.go` | httptest로 요청·응답 검증 |
| `middleware/auth.go` | RequireAuth 통과/거부 |

### 9.2 통합 테스트 (`integration_test.go`)

- 빌드 태그 `//go:build integration`
- 실제 PostgreSQL/Redis (docker compose 띄운 상태) 사용
- 가입→로그인→/me→logout 전체 플로우

### 9.3 E2E (`tests/e2e/auth_test.sh`)

```bash
#!/bin/bash
set -e
BASE=http://localhost:8080/api/v1

# 1. signup
RESP=$(curl -sf -X POST $BASE/auth/signup \
    -H 'Content-Type: application/json' \
    -d '{"email":"test@example.com","password":"Strong1234","name":"테스트"}')
TOKEN=$(echo $RESP | jq -r .access_token)
[[ -n "$TOKEN" ]] || { echo "FAIL: signup"; exit 1; }

# 2. login (중복 이메일은 409)
curl -sf -X POST $BASE/auth/signup \
    -H 'Content-Type: application/json' \
    -d '{"email":"test@example.com","password":"Strong1234","name":"중복"}' \
    && { echo "FAIL: duplicate signup should 409"; exit 1; } || echo "OK: duplicate rejected"

# 3. /me
curl -sf $BASE/auth/me -H "Authorization: Bearer $TOKEN" | jq .user.email

# 4. refresh
REFRESH=$(echo $RESP | jq -r .refresh_token)
NEW=$(curl -sf -X POST $BASE/auth/refresh \
    -H 'Content-Type: application/json' \
    -d "{\"refresh_token\":\"$REFRESH\"}")
NEW_TOKEN=$(echo $NEW | jq -r .access_token)

# 5. 이전 토큰은 그대로 유효, 새 토큰도 유효
curl -sf $BASE/auth/me -H "Authorization: Bearer $NEW_TOKEN" > /dev/null

# 6. logout-all
curl -sf -X POST $BASE/auth/logout-all -H "Authorization: Bearer $NEW_TOKEN"

# 7. refresh는 이제 401
curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/auth/refresh \
    -d "{\"refresh_token\":\"$REFRESH\"}" \
    -H 'Content-Type: application/json' | grep -q 401 || { echo "FAIL: refresh after logout-all"; exit 1; }

echo "All auth E2E tests passed."
```

---

## 10. 검증 체크리스트 (Sprint 1 종료 조건)

- [ ] 마이그레이션 0001, 0002 적용 완료, sqlc 생성 성공
- [ ] 9개 엔드포인트 모두 구현 + httptest 단위 테스트 통과
- [ ] `tests/e2e/auth_test.sh` 100% 통과
- [ ] 카카오 OAuth: 실제 카카오 콘솔 키로 authorize → callback → /me 흐름 동작
- [ ] 네이버 OAuth: 동일
- [ ] Google OAuth: 동일
- [ ] 비밀번호 5회 실패 → 잠금 → 15분 후 해제 동작
- [ ] Refresh token 회전: 사용한 토큰은 다시 사용 불가
- [ ] Logout-all: 모든 디바이스 세션이 한 번에 무효화
- [ ] Rate Limit: 60+ req/min 시 429 반환
- [ ] `go test ./internal/auth/... -race` 통과
- [ ] `golangci-lint run ./internal/auth/...` 경고 0건
- [ ] OAuth 키 발급 가이드 README 작성 완료

---

## 11. 다음 Sprint 인계 사항

Sprint 2에서 보고서 엔드포인트를 추가할 때:
- `RequireAuth` 미들웨어를 그대로 사용
- `ClaimsFromContext(ctx)`로 user_id 추출
- `auth.Service.GetUserByID(ctx, id)` (Sprint 1에서 작성)로 크레딧 잔액 확인
- `Service.DeductCredit(ctx, userID, reportID)` 메서드를 Sprint 1 마지막에 미리 작성해두면 Sprint 2 진입이 매끄러움
