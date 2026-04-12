# 05. Sprint 3 + 4 — 주소 정규화 / 사용자 / 결제 stub

> Sprint 3은 **주소 정규화 + 사용자 프로필 + PIPA**를 담당하고,
> Sprint 4는 **Toss Payments 테스트 모드 stub**을 담당한다.
>
> **선행 조건:** Sprint 1, 2 완료. 마이그레이션 0005~0007 적용.

---

## Sprint 3 — 주소 정규화 + 사용자 + PIPA

### 1. 산출물

- `internal/address/` 패키지 (Go 측 카카오 직접 호출)
- `internal/user/` 패키지 (프로필 + 사용량 + PIPA)
- `internal/api/kakao/` Go HTTP 클라이언트 (캐시·재시도)
- 7개 엔드포인트
- 마이그레이션 0005, 0006

---

### 2. Address Resolve

#### 2.1 `POST /api/v1/address/resolve`

**인증 옵션** (인터뷰 Step 2에서 비로그인 사용자도 호출 가능 — 실제 보고서 생성은 로그인 필요)

**Request:**
```json
{ "query": "마포래미안푸르지오" }
```

**Response 200:**
```json
{
  "candidates": [
    {
      "place_name": "마포래미안푸르지오",
      "address_name": "서울 마포구 아현동 699",
      "road_address": "서울 마포구 마포대로 217",
      "category": "부동산 > 아파트",
      "lat": 37.554,
      "lng": 126.951,
      "kakao_id": "12345"
    },
    ...
  ]
}
```

#### 2.2 처리 흐름

1. Rate Limit (`rl:addr:{ip}`, 60/min)
2. Redis 캐시 조회: `addr:resolve:{md5(query)}`
3. 캐시 히트 → 즉시 반환
4. 캐시 미스 → 카카오 API 호출:
   - 1차: `https://dapi.kakao.com/v2/local/search/keyword.json?query=...&category_group_code=PM2` (부동산 카테고리 우선)
   - 결과 부족 시 2차: `https://dapi.kakao.com/v2/local/search/keyword.json?query=...` (전체)
   - 여전히 부족 시 3차: `https://dapi.kakao.com/v2/local/search/address.json?query=...` (주소 검색)
5. 결과를 `AddressCandidate` 구조로 정규화 (최대 4건)
6. Redis SET TTL=30일
7. 응답

#### 2.3 Go 카카오 클라이언트 (`internal/api/kakao/client.go`)

[codes/api/clients/kakao.py](../../../../codes/api/clients/kakao.py)를 참조하여 동등한 Go 구현:

```go
type Client struct {
    apiKey  string
    httpc   *retryablehttp.Client
    cache   *cache.Redis
    limiter *rate.Limiter  // golang.org/x/time/rate
}

func NewClient(apiKey string, c *cache.Redis) *Client

func (c *Client) SearchKeyword(ctx context.Context, query string, opts SearchOptions) ([]Place, error)
func (c *Client) SearchAddress(ctx context.Context, query string) ([]Address, error)
```

- Header: `Authorization: KakaoAK {apiKey}`
- Rate Limit: 10 req/sec (Kakao 무료 한도)
- Retry: 5xx만 재시도, 최대 3회 + 지수 backoff
- 캐시 키: `kakao:keyword:{md5(query+opts)}`, TTL 7일
- 4xx는 재시도 안 함, 즉시 에러 반환

---

### 3. User Profile + Usage

#### 3.1 `GET /api/v1/user/profile`

**인증 필요.**

**Response 200:**
```json
{
  "id": "uuid",
  "email": "...",
  "name": "홍길동",
  "phone": "010-1234-5678",
  "tier": "free",
  "credits_remaining": 1,
  "auth_provider": "kakao",
  "marketing_consent": false,
  "personal_data_consent_at": "2026-04-01T00:00:00Z",
  "created_at": "..."
}
```

#### 3.2 `PUT /api/v1/user/profile`

**Request (모든 필드 옵션):**
```json
{
  "name": "새 이름",
  "phone": "010-1234-5678",
  "marketing_consent": true
}
```

**Response 200:** (업데이트된 프로필)

#### 3.3 `GET /api/v1/user/usage`

**Response 200:**
```json
{
  "tier": "free",
  "credits_remaining": 1,
  "credits_total_purchased": 0,
  "current_month": {
    "reports_generated": 1,
    "reports_completed": 1,
    "reports_failed": 0
  },
  "last_30_days": {
    "reports_generated": 1
  }
}
```

#### 3.4 `GET /api/v1/user/credit-history`

**Response 200:**
```json
{
  "entries": [
    {
      "delta": -1,
      "reason": "report_generation",
      "balance_after": 1,
      "related_report_id": "uuid",
      "created_at": "..."
    },
    {
      "delta": +2,
      "reason": "signup_bonus",
      "balance_after": 2,
      "created_at": "..."
    }
  ]
}
```

---

### 4. PIPA — 열람권 + 삭제권

#### 4.1 `GET /api/v1/user/data-export`

**인증 필요.**

**처리:**
1. `pipa_audit_log`에 `action=data_export` 기록
2. JSON 파일 생성:
   ```json
   {
     "user": { ... },
     "reports": [ ... ],
     "report_sections": [ ... ],
     "payments": [ ... ],
     "credit_ledger": [ ... ],
     "exported_at": "..."
   }
   ```
3. MinIO에 한시 업로드 → presigned URL 발급 (1시간 TTL)
4. 응답:

**Response 200:**
```json
{
  "download_url": "https://localhost:9000/realtor-reports/exports/{user_id}-{ts}.json?...",
  "expires_at": "2026-04-08T11:00:00Z"
}
```

> 또는 직접 stream으로 응답:
> `Content-Type: application/json`, `Content-Disposition: attachment; filename="my_data.json"`
> 어느 방식을 쓸지는 구현 단계에서 결정 (간단함은 stream).

#### 4.2 `DELETE /api/v1/user/account`

**인증 필요.**

**Request:**
```json
{
  "confirm_email": "user@example.com",
  "reason": "더 이상 사용하지 않음"  // 옵션
}
```

**처리:**
1. `confirm_email`이 현재 user.email과 일치하는지 검증
2. `pipa_audit_log`에 `action=deletion_request` 기록
3. `UPDATE users SET deletion_requested_at=NOW(), deletion_scheduled_at=NOW()+30d`
4. 모든 세션 revoke
5. 30일 grace period 후 별도 cron이 hard delete (Sprint 3 범위 외, Phase 5-2 cron job)

**Response 200:**
```json
{
  "message": "계정 삭제 요청이 접수되었습니다.",
  "scheduled_at": "2026-05-08T10:00:00Z",
  "cancellable_until": "2026-05-08T10:00:00Z"
}
```

#### 4.3 `POST /api/v1/user/account/cancel-deletion`

**인증 필요. (deletion_scheduled_at 이전에만 호출 가능)**

**처리:** `UPDATE users SET deletion_requested_at=NULL, deletion_scheduled_at=NULL`
+ pipa_audit_log에 기록

**Response 200:**
```json
{ "message": "계정 삭제 요청이 취소되었습니다." }
```

---

### 5. Sprint 3 환경변수

| 변수 | 필수 | 비고 |
|------|------|------|
| `KAKAO_REST_API_KEY` | ✅ | 카카오 Developer 콘솔에서 발급 (REST API 키) |

> OAuth용 KAKAO_CLIENT_ID와 다른 키. REST API용은 별도 앱으로 발급.

---

### 6. Sprint 3 검증 체크리스트

- [ ] 마이그레이션 0005, 0006 적용
- [ ] `POST /address/resolve`로 "마포래미안푸르지오" 검색 → 후보 1건 이상
- [ ] 동일 query 재호출 시 캐시 히트 (Redis MONITOR로 확인)
- [ ] `GET /user/profile`, `PUT /user/profile` 동작
- [ ] `GET /user/usage`가 정확한 카운트 반환
- [ ] `GET /user/data-export` 다운로드한 JSON에 본인 데이터 모두 포함
- [ ] `DELETE /user/account` → `deletion_scheduled_at` 설정 + 세션 revoke 확인
- [ ] `POST /user/account/cancel-deletion` 동작
- [ ] PIPA audit log에 모든 액션 기록 확인
- [ ] 다른 사용자의 user_id로 접근 시 401/403

---

## Sprint 4 — Toss Payments 결제 stub

### 1. 산출물

- `internal/payment/` 패키지 (handler, service, toss/)
- 4개 엔드포인트
- 마이그레이션 0007
- Toss API 호출은 stub 모드 기본 (`TOSS_TEST_MODE=true`)

---

### 2. Toss Payments 통합 구조

```
[프론트엔드]
   │
   │ 1. POST /payments/prepare {product_type, amount}
   ▼
[Go API] ──────────► [Toss API]
   │ 2. paymentKey 발급
   │ 3. orderId 응답
   ▼
[프론트엔드 Toss 위젯]
   │
   │ 4. 사용자가 결제 위젯에서 결제 (test mode)
   ▼
[Toss 성공 콜백 → 프론트]
   │
   │ 5. POST /payments/confirm {paymentKey, orderId, amount}
   ▼
[Go API] ──────────► [Toss confirm API]
   │ 6. 승인 확인 + DB INSERT + 크레딧 충전
   ▼
[프론트엔드: 충전 완료 화면]
```

> **Stub 모드:** `TOSS_TEST_MODE=true`이면 4단계의 Toss API 호출을 모의.
> 실제 결제 위젯 통합은 Phase 5-3 Frontend에서. Sprint 4에서는 백엔드 흐름과 DB 트랜잭션만 검증.

---

### 3. 상품 정의

`internal/payment/products.go`:

```go
type Product struct {
    Type        string  // "single_report", "credit_5", "monthly_basic", "monthly_pro"
    Name        string
    AmountKRW   int     // 원
    Credits     int     // 충전될 크레딧 수 (구독은 0, 별도 처리)
    Description string
}

var Products = map[string]Product{
    "single_report": {Type: "single_report", Name: "단건 보고서", AmountKRW: 1900, Credits: 1},
    "credit_5":      {Type: "credit_5",      Name: "5건 패키지",  AmountKRW: 7900, Credits: 5},
    // 구독은 Sprint 4 범위 외 (Phase 5-2)
}
```

---

### 4. 엔드포인트

#### 4.1 `POST /api/v1/payments/prepare`

**인증 필요.**

**Request:**
```json
{
  "product_type": "single_report",
  "idempotency_key": "uuid-from-frontend"
}
```

**처리:**
1. product_type 유효성 검증
2. idempotency_key 중복 검사 (`SELECT FROM payments WHERE user_id=$1 AND idempotency_key=$2`)
   - 중복이면 기존 결제 정보 그대로 반환
3. orderId 생성: `realtor-{user_id}-{ts}-{rand}`
4. `INSERT INTO payments (..., status='pending', amount=$amt, idempotency_key=$key)`
5. **Stub mode:** 곧바로 payment_key/order_id 반환
6. **Real mode:** Toss API `POST https://api.tosspayments.com/v1/payments` 호출
7. 응답:

**Response 200:**
```json
{
  "payment_id": "uuid",
  "order_id": "realtor-{user_id}-{ts}-{rand}",
  "amount": 1900,
  "product_name": "단건 보고서",
  "client_key": "test_ck_xxx",
  "is_test_mode": true
}
```

#### 4.2 `POST /api/v1/payments/confirm`

**인증 필요.**

**Request:**
```json
{
  "payment_id": "uuid",
  "payment_key": "tviva20...",
  "order_id": "realtor-...",
  "amount": 1900
}
```

**처리:**
1. payments 테이블에서 본인 소유, status=pending 확인
2. amount 일치 확인 (변조 방어)
3. **Stub mode:** Toss confirm 호출 생략, 즉시 success로 처리
4. **Real mode:** Toss `POST /v1/payments/confirm` 호출 + 응답 검증
5. 트랜잭션:
   - `UPDATE payments SET status='approved', approved_at=NOW(), pg_transaction_id=..., payment_method=..., webhook_payload=...`
   - `UPDATE users SET credits_remaining = credits_remaining + $credits, credits_total_purchased = credits_total_purchased + $credits`
   - `INSERT INTO credit_ledger (delta=+$credits, reason='payment', related_payment_id=...)`
6. 응답:

**Response 200:**
```json
{
  "payment_id": "uuid",
  "status": "approved",
  "credits_added": 1,
  "credits_remaining": 2,
  "receipt_url": "https://stub.example.com/receipt/..."
}
```

**Errors:**
- 400 `amount_mismatch`
- 404 `payment_not_found`
- 409 `payment_already_processed`

#### 4.3 `GET /api/v1/payments/history`

**인증 필요.**

**Query:** `?limit=20&cursor=...`

**Response 200:**
```json
{
  "payments": [
    {
      "id": "uuid",
      "product_type": "single_report",
      "amount": 1900,
      "status": "approved",
      "payment_method": "card",
      "approved_at": "...",
      "receipt_url": "..."
    }
  ],
  "next_cursor": "..."
}
```

#### 4.4 `POST /api/v1/payments/webhook`

**인증 없음. HMAC-SHA256 서명 검증.**

**Headers:**
```
Toss-Signature: sha256=<hex>
```

**처리 (실제 Toss 사용 시):**
1. body raw 읽기 → HMAC 검증
2. 이벤트 종류 파싱: `PAYMENT.DONE`, `PAYMENT.CANCELED`, `PAYMENT.FAILED`
3. payments 테이블 status 업데이트
4. 200 OK (Toss는 200이 아니면 재시도)

**Stub mode:** 엔드포인트만 존재, body 검증만 하고 200 반환

---

### 5. Toss API 클라이언트 (`internal/payment/toss/client.go`)

```go
type Client struct {
    secretKey string
    baseURL   string  // "https://api.tosspayments.com"
    httpc     *retryablehttp.Client
    testMode  bool
}

func (c *Client) Confirm(ctx context.Context, req ConfirmRequest) (*ConfirmResponse, error) {
    if c.testMode {
        return &ConfirmResponse{
            Status:        "DONE",
            PaymentKey:    req.PaymentKey,
            OrderID:       req.OrderID,
            TotalAmount:   req.Amount,
            ApprovedAt:    time.Now().Format(time.RFC3339),
            Method:        "카드",
            Card:          &CardInfo{IssuerCode: "test", AcquirerCode: "test"},
        }, nil
    }
    // 실제 호출
    // ...
}
```

Auth: HTTP Basic with `secretKey:` (콜론 포함, 비밀번호 없음)

---

### 6. Sprint 4 환경변수

| 변수 | 기본값 | 비고 |
|------|--------|------|
| `TOSS_TEST_MODE` | `true` | true면 모든 Toss 호출이 stub |
| `TOSS_CLIENT_KEY` | `test_ck_xxx` | 프론트엔드 공개 키 (응답에 포함) |
| `TOSS_SECRET_KEY` | `test_sk_xxx` | 서버 전용, Confirm 호출 시 사용 |
| `TOSS_WEBHOOK_SECRET` | (옵션) | webhook HMAC 키 |

---

### 7. Sprint 4 검증 체크리스트

- [ ] 마이그레이션 0007 적용
- [ ] `POST /payments/prepare` → payment_id + order_id 발급
- [ ] 동일 idempotency_key 재호출 → 동일 payment_id 반환
- [ ] `POST /payments/confirm` (stub mode) → status=approved + 크레딧 +1
- [ ] credit_ledger에 정상 기록
- [ ] amount 변조 → 400 amount_mismatch
- [ ] `GET /payments/history` → 본인 결제만 반환
- [ ] webhook HMAC 검증 단위 테스트 통과
- [ ] 결제 → 보고서 생성 → 잔액 0 → 결제 → 보고서 생성 전체 흐름 통과

---

## 8. Sprint 3+4 종료 후 전체 5-1 검증

[00_overview.md §7](00_overview.md#7-검증-전체-5-1-종료-조건)의 7개 시나리오가 모두 통과해야 5-1 종료.

핵심 시나리오:

```
1. 가입 (카카오 OAuth)
   ↓
2. /address/resolve로 "마포래미안푸르지오" 검색
   ↓
3. /reports로 보고서 생성 → SSE 진행률 → 완료
   ↓
4. /reports/{id}/markdown 다운로드
   ↓
5. 크레딧 0 → /payments/prepare + /confirm (stub)
   ↓
6. 두 번째 보고서 생성
   ↓
7. /user/data-export로 데이터 다운로드
   ↓
8. /user/account DELETE → 30일 후 삭제 예약 확인
```

이 시나리오는 [tests/e2e/full_flow.sh](#)로 작성하여 5-1 종료 시 1회 통과를 정식 종료 조건으로 한다.
