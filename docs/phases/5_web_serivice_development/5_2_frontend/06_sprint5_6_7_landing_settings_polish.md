# 06. Sprint 5-7 — 랜딩/설정/결제/폴리시 (12일)

> **Sprint 5 (3일):** SSG 랜딩 + 가격 페이지
> **Sprint 6 (5일):** 설정 페이지 + Toss Payments 결제 + PIPA
> **Sprint 7 (4일):** 에러 핸들링, 로딩 상태, 모바일 최적화, E2E 테스트

---

## Sprint 5 — 랜딩 + 가격 페이지 (3일)

### 1. 산출물

- `/` 랜딩 페이지 (SSG)
- `/pricing` 가격 페이지 (SSG)
- `components/landing/*` 컴포넌트
- SEO 메타태그, Open Graph

---

### 2. `/` 랜딩 페이지

#### 2.1 섹션 구성

| 순서 | 섹션 | 컴포넌트 | 내용 |
|------|------|---------|------|
| 1 | Hero | `HeroSection.tsx` | 핵심 가치 + CTA |
| 2 | 가치 제안 | `ValueProposition.tsx` | 3가지 핵심 기능 카드 |
| 3 | 이용 방법 | `HowItWorks.tsx` | 4단계 프로세스 |
| 4 | 가격 미리보기 | `PricingPreview.tsx` | 요금제 카드 요약 |
| 5 | CTA | `CTASection.tsx` | 최종 행동 유도 |
| 6 | Footer | `Footer.tsx` | 법적 링크, 사업자 정보 |

#### 2.2 Hero 섹션

```
┌─────────────────────────────────────────────┐
│                                             │
│  AI가 분석하는                                │
│  부동산 종합 보고서                            │
│                                             │
│  주소만 입력하면 시세, 입지, 세금,              │
│  투자 수익률까지 한번에 분석합니다               │
│                                             │
│  [무료로 시작하기 →]                           │
│                                             │
│        [부동산 보고서 예시 이미지]              │
│                                             │
└─────────────────────────────────────────────┘
```

- 모바일: 이미지 아래로 스택
- 데스크톱: 텍스트 좌측, 이미지 우측

#### 2.3 가치 제안 (3카드)

| 아이콘 | 제목 | 설명 |
|--------|------|------|
| ChartBar | 정확한 시세 분석 | 실거래가, KB시세 기반 현재 가치 및 추이 분석 |
| Scale | 법률/규제 점검 | 건축물대장, 토지이용규제 자동 확인 |
| BrainCircuit | AI 기반 투자 분석 | 세금 시뮬레이션, 수익률 계산, 리스크 분석 |

#### 2.4 이용 방법 (4단계)

```
① 주소 입력  →  ② 데이터 수집  →  ③ AI 분석  →  ④ 보고서 완성
   MapPin         Database         Cpu            FileText
```

#### 2.5 가격 미리보기

| 티어 | 가격 | 크레딧 |
|------|------|--------|
| 무료 | ₩0 | 2회 (가입 보너스) |
| 단건 | ₩1,900/건 | 1회 |
| 5건 패키지 | ₩7,900 | 5회 |

> 아키텍처 문서 섹션 8.3의 가격 모델 기반

---

### 3. `/pricing` 가격 페이지

상세 가격 비교표:

| 항목 | 무료 | 단건 | 5건 패키지 |
|------|------|------|-----------|
| 가격 | ₩0 | ₩1,900/건 | ₩7,900 (건당 ₩1,580) |
| 크레딧 | 2회 | 1회 | 5회 |
| 시세 분석 | ✅ | ✅ | ✅ |
| 입지 분석 | ✅ | ✅ | ✅ |
| 법률/규제 | ✅ | ✅ | ✅ |
| 투자 수익률 | ✅ | ✅ | ✅ |
| 일조/조망 | ✅ | ✅ | ✅ |
| 리스크 분석 | ✅ | ✅ | ✅ |
| 미래 전망 | ✅ | ✅ | ✅ |
| PDF 다운로드 | ❌ | ✅ | ✅ |

각 카드에 "시작하기" CTA → 미인증: `/login`, 인증: `/reports/new` 또는 `/settings` (결제)

---

### 4. SEO

#### 4.1 메타태그

```tsx
// app/page.tsx
export const metadata: Metadata = {
  title: '부동산 AI 어드바이저 — AI가 분석하는 부동산 종합 보고서',
  description: '주소만 입력하면 시세, 입지, 세금, 투자 수익률까지. 아파트, 주택 투자 분석 보고서를 AI가 자동으로 생성합니다.',
  keywords: ['부동산 분석', '아파트 시세', '부동산 AI', '투자 분석', '부동산 보고서'],
  openGraph: {
    title: '부동산 AI 어드바이저',
    description: 'AI가 분석하는 부동산 종합 보고서',
    locale: 'ko_KR',
    type: 'website',
  },
};
```

#### 4.2 구조화 데이터 (JSON-LD)

```tsx
<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{
    __html: JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: '부동산 AI 어드바이저',
      applicationCategory: 'FinanceApplication',
      operatingSystem: 'Web',
      offers: {
        '@type': 'Offer',
        price: '0',
        priceCurrency: 'KRW',
      },
    }),
  }}
/>
```

### 5. Sprint 5 검증 체크리스트

- [ ] `next build` → `/`와 `/pricing` SSG HTML 생성
- [ ] Lighthouse Performance 90+, SEO 90+, Accessibility 90+
- [ ] 모바일 (375px): Hero 스택, 카드 단일 컬럼
- [ ] CTA 클릭 → 미인증: `/login`, 인증: `/reports/new`
- [ ] Open Graph 메타태그 확인 (SNS 공유 미리보기)

---

## Sprint 6 — 설정 + 결제 (5일)

### 6. 산출물

- `/settings` 페이지 (4개 탭: 프로필/이용내역/결제/계정)
- `TossPaymentWidget.tsx` Toss Payments SDK 통합
- PIPA 데이터 내보내기 + 계정 삭제 UI
- `queries/payments.ts`, `types/payment.ts`

---

### 7. `/settings` 페이지 구조

```
┌─────────────────────────────────────────────┐
│  설정                                        │
│                                             │
│  [프로필] [이용 내역] [크레딧 충전] [계정]    │  ← 탭
│  ─────────────────────────────────────────── │
│                                             │
│  {현재 탭 내용}                               │
│                                             │
└─────────────────────────────────────────────┘
```

모바일: 가로 스크롤 탭 또는 전체 너비 세그먼트

### 8. 탭 상세

#### 8.1 프로필 탭 (`settings/ProfileSection.tsx`)

| 필드 | 타입 | 편집 |
|------|------|------|
| 이름 | 텍스트 | ✅ |
| 이메일 | 텍스트 | ❌ (읽기 전용) |
| 전화번호 | 텍스트 | ✅ |
| 로그인 방식 | 뱃지 | ❌ (표시만) |
| 마케팅 동의 | 토글 | ✅ |

- `GET /api/v1/user/profile` → 조회
- `PUT /api/v1/user/profile` → 저장 (변경된 필드만)
- "비밀번호 변경" 버튼 (email 가입자만 표시) → `POST /api/v1/auth/change-password`

#### 8.2 이용 내역 탭 (`settings/UsageTab.tsx`)

- `GET /api/v1/user/usage` → 사용량 요약 카드
- `GET /api/v1/user/credit-history` → 크레딧 내역 테이블

```
┌──────────┬──────────┬──────────┐
│ 잔여 크레딧│ 총 구매   │ 이번 달    │
│    3건    │   5건    │  2건 생성  │
└──────────┴──────────┴──────────┘

크레딧 내역:
날짜          | 변동 | 사유          | 잔여
2026-04-10   | -1  | 보고서 생성    | 3
2026-04-08   | +5  | 5건 패키지 구매 | 4
2026-04-01   | +2  | 가입 보너스    | 2  (필터 가능 구간은 아님)
```

#### 8.3 크레딧 충전 탭 (`payment/TossPaymentWidget.tsx`)

**Toss Payments 통합 전체 흐름:**

```
[사용자]                  [프론트엔드]              [Go API]             [Toss API]
   │                         │                       │                     │
   ├─ "단건 ₩1,900" 클릭     │                       │                     │
   │                         ├─ POST /payments/prepare│                     │
   │                         │  { product_type:       │                     │
   │                         │    "single_report",    │                     │
   │                         │    idempotency_key }   │                     │
   │                         │ ─────────────────────► │                     │
   │                         │                       ├─ Toss API 세션 생성  │
   │                         │                       │ ──────────────────► │
   │                         │ ◄──────────────────── │                     │
   │                         │  { clientKey, orderId, │                     │
   │                         │    orderName, amount } │                     │
   │                         │                       │                     │
   │                         ├─ Toss SDK 위젯 렌더링  │                     │
   │  ◄─ 결제 위젯 표시       │                       │                     │
   │                         │                       │                     │
   ├─ 카드/카카오페이/        │                       │                     │
   │  네이버페이 선택+결제     │                       │                     │
   │                         │                       │                     │
   │  → Toss 성공 콜백       │                       │                     │
   │                         ├─ POST /payments/confirm│                     │
   │                         │  { paymentKey,         │                     │
   │                         │    orderId, amount }   │                     │
   │                         │ ─────────────────────► │                     │
   │                         │                       ├─ Toss 서버간 승인 확인│
   │                         │                       │ ──────────────────► │
   │                         │                       ├─ 크레딧 충전         │
   │                         │ ◄──────────────────── │                     │
   │                         │  { credits_remaining } │                     │
   │                         │                       │                     │
   │  ◄─ "충전 완료!" 토스트   │                       │                     │
```

**Toss SDK 초기화:**

```typescript
import { loadTossPayments } from '@tosspayments/tosspayments-sdk';

async function initPayment(clientKey: string, orderId: string, orderName: string, amount: number) {
  const tossPayments = await loadTossPayments(clientKey);
  const payment = tossPayments.payment({ customerKey: userId });

  await payment.requestPayment({
    method: '카드',           // 또는 'CARD'
    amount: { value: amount, currency: 'KRW' },
    orderId,
    orderName,
    successUrl: `${window.location.origin}/settings?tab=payment&status=success`,
    failUrl: `${window.location.origin}/settings?tab=payment&status=fail`,
  });
}
```

**상품 목록:**

| 코드 | 이름 | 가격 | 크레딧 |
|------|------|------|--------|
| `single_report` | 단건 보고서 | ₩1,900 | 1 |
| `credit_5` | 5건 패키지 | ₩7,900 | 5 |

#### 8.4 계정 탭 (`settings/DataPrivacyActions.tsx`)

**데이터 내보내기:**
- "내 데이터 내보내기" 버튼 → `GET /api/v1/user/data-export` → JSON 파일 다운로드
- 로딩 스피너 표시 (서버 측 JSON 조립 시간)

**계정 삭제:**
- "계정 삭제" 버튼 → 확인 Dialog (이메일 입력 필수)
- `DELETE /api/v1/user/account` → { confirm_email, reason }
- 30일 유예 기간 안내: "30일 이내에 철회할 수 있습니다"
- 삭제 요청 후 → 로그아웃 → `/login`

**삭제 철회:**
- 삭제 요청 상태에서 로그인 → "계정 삭제가 예정되어 있습니다" 배너
- "삭제 철회" 버튼 → `POST /api/v1/user/account/cancel-deletion`

---

### 9. 백엔드 API 연동 (Sprint 6)

| 엔드포인트 | 용도 | 탭 |
|-----------|------|-----|
| `GET /api/v1/user/profile` | 프로필 조회 | 프로필 |
| `PUT /api/v1/user/profile` | 프로필 수정 | 프로필 |
| `POST /api/v1/auth/change-password` | 비밀번호 변경 | 프로필 |
| `GET /api/v1/user/usage` | 사용량 | 이용내역 |
| `GET /api/v1/user/credit-history` | 크레딧 내역 | 이용내역 |
| `POST /api/v1/payments/prepare` | 결제 세션 생성 | 충전 |
| `POST /api/v1/payments/confirm` | 결제 승인 | 충전 |
| `GET /api/v1/payments/history` | 결제 내역 | 충전 |
| `GET /api/v1/user/data-export` | 데이터 내보내기 | 계정 |
| `DELETE /api/v1/user/account` | 계정 삭제 | 계정 |
| `POST /api/v1/user/account/cancel-deletion` | 삭제 철회 | 계정 |

### 10. Sprint 6 검증 체크리스트

- [ ] 프로필 수정 → 저장 → 반영 확인
- [ ] 비밀번호 변경 (email 가입자) 동작
- [ ] 크레딧 내역 테이블 정확한 값
- [ ] Toss 테스트 모드 결제 → 위젯 렌더링 → 결제 완료 → 크레딧 증가
- [ ] 결제 실패 → 에러 토스트
- [ ] 데이터 내보내기 → JSON 파일 다운로드
- [ ] 계정 삭제 → 이메일 확인 → 30일 유예 안내 → 로그아웃
- [ ] 삭제 유예 중 → 로그인 → "삭제 예정" 배너 + 철회 버튼
- [ ] 삭제 철회 → 정상 계정 복원
- [ ] 모바일 (375px): 탭 가로 스크롤, 폼 사용 가능

---

## Sprint 7 — 폴리시 (4일)

### 11. 에러 핸들링

#### 11.1 전역 에러 바운더리

`app/error.tsx`:
```tsx
'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="text-center">
        <h1 className="text-2xl font-bold mb-2">문제가 발생했습니다</h1>
        <p className="text-gray-500 mb-6">
          잠시 후 다시 시도해주세요.
          문제가 지속되면 고객센터로 문의해주세요.
        </p>
        <button onClick={reset} className="btn-primary">
          다시 시도
        </button>
      </div>
    </div>
  );
}
```

#### 11.2 API 에러 토스트

```typescript
// TanStack Query 전역 에러 핸들러
const queryClient = new QueryClient({
  defaultOptions: {
    mutations: {
      onError: (error) => {
        if (error instanceof ApiError) {
          toast.error(error.userMessage);
        }
      },
    },
  },
});
```

#### 11.3 한국어 에러 메시지 매핑

| HTTP 상태 | 코드 | 메시지 |
|----------|------|--------|
| 400 | `invalid_email` | "이메일 형식이 올바르지 않습니다" |
| 400 | `weak_password` | "비밀번호는 8자 이상이어야 합니다" |
| 400 | `address_input_required` | "주소를 입력해주세요" |
| 400 | `invalid_purpose` | "분석 목적을 선택해주세요" |
| 401 | `invalid_credentials` | "이메일 또는 비밀번호가 올바르지 않습니다" |
| 401 | `account_locked` | "계정이 잠겼습니다. 잠시 후 다시 시도해주세요" |
| 402 | `insufficient_credits` | "크레딧이 부족합니다" |
| 409 | `email_already_exists` | "이미 가입된 이메일입니다" |
| 429 | `rate_limit_exceeded` | "요청이 너무 많습니다. 잠시 후 다시 시도해주세요" |

---

### 12. 로딩 상태

#### 12.1 스켈레톤

각 페이지별 Skeleton 컴포넌트:
- `dashboard/page.tsx` → 카드 3개 스켈레톤 + 보고서 목록 스켈레톤
- `reports/[id]/page.tsx` → 프로그레스 바 스켈레톤 또는 섹션 스켈레톤
- `settings/page.tsx` → 프로필 폼 스켈레톤

#### 12.2 버튼 로딩 스피너

모든 폼 제출 버튼: 제출 중 `disabled` + Loader2 아이콘 spin

#### 12.3 빈 상태

| 페이지 | 조건 | 표시 |
|--------|------|------|
| 대시보드 | 보고서 0건 | "아직 생성된 보고서가 없습니다" + CTA |
| 이용내역 | 크레딧 내역 0건 | "크레딧 사용 내역이 없습니다" |
| 결제내역 | 결제 0건 | "결제 내역이 없습니다" |

---

### 13. 모바일 최적화

#### 13.1 터치 타겟

모든 인터랙티브 요소 최소 44x44px (WCAG 2.5.8 권장)

#### 13.2 375px 기준 레이아웃

| 요소 | 모바일 처리 |
|------|-----------|
| Header | 햄버거 메뉴 → Sheet 슬라이드아웃 |
| 대시보드 카드 | 단일 컬럼 스택 |
| 인터뷰 목적 카드 | 2열 그리드 유지 (카드 크기 축소) |
| 보고서 TOC | Sheet 컴포넌트 (좌측 슬라이드) |
| 설정 탭 | 가로 스크롤 또는 세그먼트 |
| 테이블 | 가로 스크롤 래퍼 |

#### 13.3 `next/image` 최적화

```tsx
<Image
  src="/images/hero-property.webp"
  alt="부동산 분석 보고서 예시"
  width={600}
  height={400}
  sizes="(max-width: 768px) 100vw, 50vw"
  priority  // Hero 이미지는 LCP 대상
/>
```

---

### 14. E2E 테스트 (Playwright)

#### 14.1 전체 사용자 여정

```typescript
// tests/e2e/full-journey.spec.ts
test('complete user journey', async ({ page }) => {
  // 1. 랜딩 페이지
  await page.goto('/');
  await expect(page.getByText('부동산 AI 분석 보고서')).toBeVisible();

  // 2. 로그인 (이메일)
  await page.goto('/login');
  await page.fill('[name=email]', 'test@example.com');
  await page.fill('[name=password]', 'Test1234!');
  await page.click('button:has-text("이메일로 로그인")');
  await expect(page).toHaveURL('/dashboard');

  // 3. 대시보드
  await expect(page.getByText('내 보고서')).toBeVisible();

  // 4. 인터뷰 시작
  await page.click('text=새 보고서 생성');
  await expect(page).toHaveURL('/reports/new');

  // 5. Step 1: 주소 입력
  await page.fill('input', '마포래미안푸르지오');
  await page.click('button:has-text("다음")');

  // 6. Step 2: 후보 선택
  await page.click('[data-testid="candidate-0"]');
  await page.click('button:has-text("다음")');

  // 7. Step 3: 목적 선택
  await page.click('text=매매 — 구매 (실거주)');
  await page.click('button:has-text("다음")');

  // 8. Step 4: 확인 + 생성
  await page.click('button:has-text("보고서 생성 시작")');

  // 9. 진행률 확인
  await expect(page.getByText('보고서 생성 중')).toBeVisible();

  // 10. 완료 대기 (최대 120초)
  await expect(page.getByText('부동산 딥 리포트')).toBeVisible({ timeout: 120000 });

  // 11. 보고서 섹션 확인
  await expect(page.getByText('입지 분석')).toBeVisible();
  await expect(page.getByText('가격/시세 분석')).toBeVisible();
});
```

#### 14.2 모바일 뷰포트 테스트

```typescript
// tests/e2e/mobile.spec.ts
test.use({ viewport: { width: 375, height: 812 } }); // iPhone 13 mini

test('mobile interview flow', async ({ page }) => {
  // ... 동일한 플로우를 375px에서 수행
});
```

#### 14.3 에러 시나리오

```typescript
test('handles API errors gracefully', async ({ page }) => {
  // MSW로 API 503 응답 모킹
  // 에러 토스트 표시 확인
  // 재시도 버튼 동작 확인
});
```

---

### 15. Sprint 7 검증 체크리스트

- [ ] 전역 에러 바운더리: 렌더링 에러 시 "문제가 발생했습니다" + 재시도
- [ ] API 에러 → 한국어 토스트 메시지
- [ ] 모든 페이지 스켈레톤 로딩 표시
- [ ] 빈 상태 UI 모든 경우 확인
- [ ] 모바일 (375px): 전체 플로우 사용 가능
- [ ] 터치 타겟 44px+ (Lighthouse 접근성 확인)
- [ ] 키보드 내비게이션: Tab/Enter/Escape 동작
- [ ] `next/image` 사용, LCP 이미지 `priority` 설정
- [ ] Playwright E2E: 전체 사용자 여정 통과
- [ ] Playwright E2E: 모바일 375px 통과
- [ ] Lighthouse Performance 90+, Accessibility 95+, Best Practices 90+, SEO 90+
- [ ] `npm run build` 성공, `npm run lint` 통과, `npm run test` 통과
