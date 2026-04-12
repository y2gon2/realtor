# 01. 기술 스택 & 프로젝트 구조

> **목표:** 프론트엔드 기술 선택의 근거를 명시하고, 디렉토리 구조, API 클라이언트 설계,
> 디자인 토큰, 접근성 전략을 정의한다.

---

## 1. 라이브러리 선택 근거

### 1.1 코어 프레임워크

| 카테고리 | 선택 | 대안 | 선택 이유 |
|---------|------|------|----------|
| 프레임워크 | Next.js 15 (App Router) | Vite + React Router | SSG(랜딩/가격) + CSR(대시보드) 혼합 필요. SEO 필수 페이지 존재 |
| 언어 | TypeScript 5.x (strict) | JavaScript | API 계약 타입 안전, 백엔드 응답 구조 미러링 |
| 스타일링 | Tailwind CSS v4 | styled-components, CSS Modules | 모바일 퍼스트 유틸리티, 디자인 토큰 CSS 변수 지원, 번들 최소 |
| 린팅 | ESLint + @next/eslint-plugin-next | — | CI 파이프라인 통합 (아키텍처 문서 섹션 10.1) |

### 1.2 UI 컴포넌트

| 카테고리 | 선택 | 대안 | 선택 이유 |
|---------|------|------|----------|
| 프리미티브 | shadcn/ui + @radix-ui | Ant Design, MUI, Headless UI | **코드 소유** — 한국 소셜 로그인 버튼 브랜드 가이드라인(카카오 #FEE500, 네이버 #03C75A) 픽셀 단위 맞춤 가능. Ant/MUI는 고유 스타일 강제로 한국어 타이포그래피·간격과 충돌 |
| 아이콘 | lucide-react | heroicons, react-icons | 트리 셰이킹 지원, 일관된 스트로크 스타일 |
| 토스트 | sonner | react-hot-toast, radix Toast | 경량, React 19 호환, 프로미스 기반 API |

### 1.3 상태 관리 & 데이터 페칭

| 카테고리 | 선택 | 대안 | 선택 이유 |
|---------|------|------|----------|
| 서버 상태 | @tanstack/react-query v5 | SWR, 직접 fetch | 캐싱, 리패칭, 뮤테이션, `useInfiniteQuery`(커서 페이지네이션). API 호출 래퍼 불필요 |
| 클라이언트 상태 | Zustand | Redux Toolkit, Context API | 인터뷰 위자드 다단계 상태 관리. Context는 prop drilling 해결만, Zustand는 선택적 리렌더링 + devtools 제공. Redux는 MVP 규모에서 과도 |
| 폼 핸들링 | react-hook-form v7 + zod | Formik, 직접 useState | 비제어 컴포넌트 기반(리렌더링 최소), zod 스키마로 API 타입과 검증 일치 |

### 1.4 콘텐츠 렌더링

| 카테고리 | 선택 | 대안 | 선택 이유 |
|---------|------|------|----------|
| 마크다운 | react-markdown + remark-gfm + rehype-raw | MDX, unified 직접 | 보고서는 서버 생성 마크다운이므로 MDX 불필요. GFM 테이블, 차트 이미지(base64 PNG) 렌더링 필요 |
| 차트 | 없음 (백엔드 이미지 사용) | Recharts, Chart.js | Python Worker(matplotlib)가 2x DPI PNG 생성. 클라이언트 재렌더링은 원본 데이터 미제공+한국어 폰트 불일치로 불가 |
| 애니메이션 | Framer Motion | CSS only, react-spring | 인터뷰 스텝 전환, SSE 프로그레스 스텝 순차 공개에 `AnimatePresence` + `motion.div` 필수 |

### 1.5 결제

| 카테고리 | 선택 | 비고 |
|---------|------|------|
| Toss SDK | @tosspayments/tosspayments-sdk | 공식 JS SDK. PCI SAQ-A (카드 데이터 서버 미경유) |

### 1.6 테스트

| 카테고리 | 선택 | 비고 |
|---------|------|------|
| 단위/컴포넌트 | vitest + @testing-library/react | ESM 네이티브, CI 빠름 (아키텍처 문서: "eslint → vitest → next build") |
| E2E | Playwright | 크로스 브라우저, 모바일 뷰포트 테스트 |
| API 모킹 | MSW (Mock Service Worker) v2 | 백엔드 미완 시 개발 계속 가능 |

### 1.7 개발 도구

| 카테고리 | 선택 | 비고 |
|---------|------|------|
| 쿼리 디버깅 | @tanstack/react-query-devtools | 개발 빌드 전용, 캐시 상태 시각화 |
| API 타입 | 수동 타입 정의 | 백엔드 OpenAPI 스펙 미제공. 백엔드 문서 기반으로 `src/types/`에 수동 작성 |

---

## 2. 프로젝트 디렉토리 구조

```
codes/realtor-ai-frontend/
├── .env.local                     # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_STORAGE_URL
├── .env.example                   # 환경변수 템플릿 (git 추적)
├── .eslintrc.json
├── .gitignore
├── Dockerfile                     # 프로덕션 멀티스테이지 빌드
├── next.config.ts
├── package.json
├── tailwind.config.ts
├── tsconfig.json
├── vitest.config.ts
│
├── public/
│   ├── favicon.ico
│   ├── fonts/                     # Pretendard WOFF2 (자체 호스팅)
│   └── images/
│       ├── hero-property.webp     # 랜딩 Hero 이미지
│       ├── kakao-logo.svg         # 소셜 로그인 아이콘
│       ├── naver-logo.svg
│       └── google-logo.svg
│
├── src/
│   ├── app/                       # Next.js App Router
│   │   ├── layout.tsx             # 루트 레이아웃 (<html lang="ko">, 폰트, Providers)
│   │   ├── page.tsx               # 랜딩 (SSG)
│   │   ├── not-found.tsx          # 404
│   │   ├── error.tsx              # 전역 에러 바운더리
│   │   │
│   │   ├── pricing/
│   │   │   └── page.tsx           # 요금제 (SSG)
│   │   │
│   │   ├── login/
│   │   │   └── page.tsx           # 로그인
│   │   │
│   │   ├── auth/
│   │   │   └── callback/
│   │   │       └── page.tsx       # OAuth 콜백 핸들러
│   │   │
│   │   ├── (protected)/           # 라우트 그룹 (인증 필요)
│   │   │   ├── layout.tsx         # AuthGuard 래퍼
│   │   │   ├── dashboard/
│   │   │   │   └── page.tsx
│   │   │   ├── reports/
│   │   │   │   ├── new/
│   │   │   │   │   └── page.tsx   # 인터뷰 위자드
│   │   │   │   └── [id]/
│   │   │   │       └── page.tsx   # 보고서 뷰어 + SSE 진행률
│   │   │   └── settings/
│   │   │       └── page.tsx
│   │   │
│   │   └── globals.css            # Tailwind 디렉티브, 폰트, 글로벌 스타일
│   │
│   ├── components/
│   │   ├── ui/                    # shadcn/ui 프리미티브
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── progress.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── sheet.tsx          # 모바일 슬라이드아웃 (TOC용)
│   │   │   ├── tabs.tsx
│   │   │   ├── table.tsx
│   │   │   ├── skeleton.tsx
│   │   │   └── textarea.tsx
│   │   │
│   │   ├── layout/                # 구조 컴포넌트
│   │   │   ├── Header.tsx         # 상단 네비게이션
│   │   │   ├── Footer.tsx         # 하단 (법적 링크)
│   │   │   ├── MobileNav.tsx      # 햄버거 메뉴
│   │   │   └── Container.tsx      # max-width 래퍼
│   │   │
│   │   ├── auth/                  # 인증 컴포넌트
│   │   │   ├── SocialLoginButtons.tsx
│   │   │   ├── EmailLoginForm.tsx
│   │   │   ├── SignupForm.tsx
│   │   │   └── ConsentCheckbox.tsx
│   │   │
│   │   ├── interview/             # 인터뷰 위자드
│   │   │   ├── InterviewWizard.tsx     # 스텝 오케스트레이터
│   │   │   ├── StepIndicator.tsx       # 진행 표시 (1/4, 2/4 ...)
│   │   │   ├── StepAddressInput.tsx    # Step 1
│   │   │   ├── StepAddressConfirm.tsx  # Step 2
│   │   │   ├── StepPurposeSelect.tsx   # Step 3
│   │   │   ├── StepSummary.tsx         # Step 4
│   │   │   ├── AddressCandidateCard.tsx
│   │   │   └── PurposeCard.tsx
│   │   │
│   │   ├── report/                # 보고서 관련
│   │   │   ├── ReportProgress.tsx      # SSE 진행률 표시
│   │   │   ├── ProgressStepList.tsx    # 7단계 스텝 리스트
│   │   │   ├── ProgressBar.tsx         # 애니메이션 프로그레스 바
│   │   │   ├── ReportViewer.tsx        # 완료된 보고서 뷰어
│   │   │   ├── ReportSidebar.tsx       # 데스크톱 TOC (sticky)
│   │   │   ├── ReportMobileTOC.tsx     # 모바일 TOC (Sheet)
│   │   │   ├── ReportSection.tsx       # 단일 섹션 렌더러
│   │   │   ├── MarkdownRenderer.tsx    # react-markdown 래퍼
│   │   │   └── ReportActions.tsx       # 인쇄/다운로드/공유
│   │   │
│   │   ├── dashboard/             # 대시보드
│   │   │   ├── ReportList.tsx
│   │   │   ├── ReportCard.tsx
│   │   │   ├── UsageStats.tsx
│   │   │   ├── StatusFilter.tsx
│   │   │   └── EmptyState.tsx
│   │   │
│   │   ├── payment/               # 결제
│   │   │   ├── TossPaymentWidget.tsx
│   │   │   └── PricingCard.tsx
│   │   │
│   │   ├── settings/              # 설정
│   │   │   ├── ProfileSection.tsx
│   │   │   ├── UsageTab.tsx
│   │   │   ├── PaymentHistory.tsx
│   │   │   └── DataPrivacyActions.tsx
│   │   │
│   │   └── landing/               # 랜딩 페이지
│   │       ├── HeroSection.tsx
│   │       ├── ValueProposition.tsx
│   │       ├── HowItWorks.tsx
│   │       ├── PricingPreview.tsx
│   │       └── CTASection.tsx
│   │
│   ├── hooks/                     # 커스텀 훅
│   │   ├── useAuth.ts             # 인증 상태 + login/logout
│   │   ├── useEventSource.ts      # SSE 연결 관리
│   │   ├── useReportProgress.ts   # 특정 보고서 SSE 진행률
│   │   ├── useMediaQuery.ts       # 반응형 브레이크포인트
│   │   └── useScrollSpy.ts        # TOC 활성 섹션 추적
│   │
│   ├── lib/                       # 유틸리티
│   │   ├── api-client.ts          # fetch 래퍼 (토큰 주입, 리프레시, 에러)
│   │   ├── auth.ts                # 토큰 저장/리프레시/클리어
│   │   ├── constants.ts           # 목적 선택지, 진행 스텝, 섹션 타입
│   │   ├── cn.ts                  # clsx + tailwind-merge
│   │   └── validators.ts          # zod 스키마 (폼 검증)
│   │
│   ├── stores/                    # Zustand 스토어
│   │   └── interview-store.ts     # 인터뷰 다단계 상태
│   │
│   ├── queries/                   # TanStack Query 정의
│   │   ├── auth.ts                # useMe, useLogin, useSignup
│   │   ├── reports.ts             # useReports, useReport, useCreateReport
│   │   ├── address.ts             # useResolveAddress
│   │   ├── user.ts                # useProfile, useUsage, useCreditHistory
│   │   └── payments.ts            # usePreparePayment, useConfirmPayment
│   │
│   ├── types/                     # API 응답 타입 (백엔드 미러링)
│   │   ├── auth.ts                # User, Session, LoginRequest
│   │   ├── report.ts              # Report, ReportSection, ProgressEvent
│   │   ├── address.ts             # AddressCandidate, ResolveResponse
│   │   ├── user.ts                # UserProfile, UsageStats, CreditEntry
│   │   └── payment.ts             # PaymentPrepare, PaymentConfirm, Product
│   │
│   ├── providers/                 # React 컨텍스트 프로바이더
│   │   ├── QueryProvider.tsx      # TanStack Query
│   │   └── AuthProvider.tsx       # 인증 컨텍스트
│   │
│   └── middleware.ts              # Next.js 미들웨어 (라우트 보호)
│
└── tests/
    ├── unit/                      # vitest 컴포넌트 테스트
    ├── integration/               # API 모킹 통합 테스트
    └── e2e/                       # Playwright E2E
```

---

## 3. API 클라이언트 설계

### 3.1 `lib/api-client.ts`

모든 API 호출의 단일 진입점. 토큰 주입, 401 자동 리프레시, 에러 정규화를 담당.

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL; // http://localhost:8080

class ApiClient {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  setTokens(access: string, refresh: string) {
    this.accessToken = access;
    this.refreshToken = refresh;
  }

  clearTokens() {
    this.accessToken = null;
    this.refreshToken = null;
  }

  async fetch<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    if (this.accessToken) {
      headers.set('Authorization', `Bearer ${this.accessToken}`);
    }
    if (!headers.has('Content-Type') && init?.body) {
      headers.set('Content-Type', 'application/json');
    }

    const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

    // 401 → 자동 리프레시 → 재시도
    if (res.status === 401 && this.refreshToken) {
      const refreshed = await this.tryRefresh();
      if (refreshed) {
        headers.set('Authorization', `Bearer ${this.accessToken}`);
        const retry = await fetch(`${API_BASE}${path}`, { ...init, headers });
        if (!retry.ok) throw new ApiError(retry);
        return retry.status === 204 ? (undefined as T) : retry.json();
      }
      window.location.href = '/login';
      throw new ApiError(res, 'session_expired');
    }

    if (!res.ok) throw new ApiError(res);
    return res.status === 204 ? (undefined as T) : res.json();
  }

  private async tryRefresh(): Promise<boolean> {
    // 동시 다발 401에 대한 단일 리프레시 보장
    if (this.refreshPromise) return this.refreshPromise;
    this.refreshPromise = this.doRefresh();
    const result = await this.refreshPromise;
    this.refreshPromise = null;
    return result;
  }

  private async doRefresh(): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: this.refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      this.setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    }
  }

  // SSE용 토큰 (쿼리 파라미터)
  getAccessToken(): string | null {
    return this.accessToken;
  }
}

export const apiClient = new ApiClient();
```

### 3.2 에러 정규화

```typescript
class ApiError extends Error {
  status: number;
  code: string;
  detail: string;

  constructor(res: Response, code?: string) {
    super(`API Error: ${res.status}`);
    this.status = res.status;
    this.code = code ?? 'unknown';
    this.detail = '';
  }

  // 한국어 에러 메시지 매핑
  get userMessage(): string {
    const messages: Record<number, string> = {
      400: '입력값을 확인해주세요',
      401: '로그인이 필요합니다',
      402: '크레딧이 부족합니다',
      403: '접근 권한이 없습니다',
      404: '페이지를 찾을 수 없습니다',
      429: '요청이 너무 많습니다. 잠시 후 다시 시도해주세요',
      500: '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요',
    };
    return messages[this.status] ?? '알 수 없는 오류가 발생했습니다';
  }
}
```

---

## 4. 디자인 토큰

### 4.1 색상

```css
:root {
  /* Primary — 전문적 네이비 블루 */
  --color-primary-50: #EFF6FF;
  --color-primary-100: #DBEAFE;
  --color-primary-500: #2563EB;    /* 주 액션 */
  --color-primary-600: #1D4ED8;
  --color-primary-700: #1E3A5F;    /* 헤더, 사이드바 */
  --color-primary-900: #0F172A;

  /* 액센트 — 따뜻한 골드 (CTA, 하이라이트) */
  --color-accent-400: #FBBF24;
  --color-accent-500: #F59E0B;

  /* 시맨틱 */
  --color-success: #059669;        /* 완료 */
  --color-warning: #D97706;        /* 진행 중 */
  --color-error: #DC2626;          /* 실패 */

  /* 한국 부동산 관례 */
  --color-price-up: #E74C3C;       /* 빨간색 = 가격 상승 */
  --color-price-down: #3498DB;     /* 파란색 = 가격 하락 */

  /* 소셜 로그인 브랜드 */
  --color-kakao: #FEE500;
  --color-kakao-text: #000000;
  --color-naver: #03C75A;
  --color-naver-text: #FFFFFF;
  --color-google-border: #DADCE0;

  /* 뉴트럴 */
  --color-gray-50: #F9FAFB;
  --color-gray-100: #F3F4F6;
  --color-gray-200: #E5E7EB;
  --color-gray-400: #9CA3AF;
  --color-gray-500: #6B7280;
  --color-gray-600: #4B5563;
  --color-gray-700: #374151;
  --color-gray-800: #1F2937;
  --color-gray-900: #111827;

  /* 서피스 */
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F9FAFB;
  --color-bg-tertiary: #F3F4F6;
}
```

### 4.2 타이포그래피

```css
:root {
  /* 폰트 패밀리 */
  --font-sans: 'Pretendard Variable', 'Pretendard', -apple-system,
               BlinkMacSystemFont, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* 타입 스케일 (모바일 퍼스트) */
  --text-xs: 0.75rem;      /* 12px — 캡션, 뱃지 */
  --text-sm: 0.875rem;     /* 14px — 부가 텍스트, 테이블 셀 */
  --text-base: 1rem;       /* 16px — 본문 */
  --text-lg: 1.125rem;     /* 18px — 섹션 소제목 */
  --text-xl: 1.25rem;      /* 20px — 카드 타이틀 */
  --text-2xl: 1.5rem;      /* 24px — 페이지 타이틀 (모바일) */
  --text-3xl: 1.875rem;    /* 30px — 페이지 타이틀 (데스크톱) */
  --text-4xl: 2.25rem;     /* 36px — Hero 헤드라인 */
  --text-5xl: 3rem;        /* 48px — 랜딩 Hero (데스크톱) */

  /* 행간 — 한국어는 1.5 이상 필요 */
  --leading-tight: 1.25;    /* 헤딩 */
  --leading-normal: 1.5;    /* 본문 */
  --leading-relaxed: 1.75;  /* 보고서 장문 */

  /* 폰트 웨이트 */
  --font-regular: 400;
  --font-medium: 500;
  --font-semibold: 600;
  --font-bold: 700;
}
```

**Pretendard 선택 이유:**
- 가변 폰트 단일 파일 (~5MB WOFF2 서브셋) vs Noto Sans KR 7 웨이트 (~15MB)
- 한국어 UI 텍스트용 자간 최적화
- 라틴-한글 조화 우수
- `next/font/local`로 로드, `display: swap` 설정

### 4.3 간격

8px 기반 그리드:

| 토큰 | 값 | 용도 |
|------|-----|------|
| `space-1` | 4px | 인라인 간격 |
| `space-2` | 8px | 아이콘-텍스트 간격 |
| `space-3` | 12px | 소형 패딩 |
| `space-4` | 16px | 기본 패딩 |
| `space-6` | 24px | 카드 패딩 |
| `space-8` | 32px | 섹션 간격 |
| `space-12` | 48px | 대형 섹션 간격 |
| `space-16` | 64px | 페이지 간격 |

### 4.4 반응형 브레이크포인트

모바일 퍼스트. 기본값은 모바일.

| 브레이크포인트 | Tailwind | 너비 | 대상 |
|-------------|---------|------|------|
| 기본 | (없음) | 0-639px | 모바일 (375px 기준) |
| `sm` | `sm:` | 640px+ | 대형 폰/소형 태블릿 |
| `md` | `md:` | 768px+ | 태블릿 세로 |
| `lg` | `lg:` | 1024px+ | 태블릿 가로/데스크톱 |
| `xl` | `xl:` | 1280px+ | 와이드 데스크톱 |

**페이지별 반응형 동작:**

| 페이지 | 모바일 (<md) | 데스크톱 (>=lg) |
|--------|------------|---------------|
| 인터뷰 | 단일 컬럼, max-w-640px 중앙 | 동일 (항상 단일 컬럼) |
| 보고서 뷰어 | 접이식 TOC (상단), 스태킹 | 사이드바 TOC (280px sticky) + 콘텐츠 |
| 대시보드 | 단일 컬럼 카드 | 2~3 컬럼 그리드 |
| 랜딩 | 스택 섹션 | 사이드 바이 사이드 Hero |
| 설정 | 스택 탭 | 사이드 탭 내비게이션 |

---

## 5. 접근성 전략

### 5.1 한국어 스크린 리더 호환

주요 한국어 스크린 리더: **센스리더(SenseReader)** (한국 최다 사용), **NVDA** (한국어 TTS), **VoiceOver** (macOS/iOS)

### 5.2 ARIA 전략

- shadcn/ui + Radix UI가 기본 ARIA 속성 제공 (Dialog, Sheet, Tabs, Progress 등)
- **프로그레스 바:** `role="progressbar"` + `aria-valuenow`, `aria-valuemin`, `aria-valuemax`
- **SSE 진행률:** `role="status"` + `aria-live="polite"` (진행 중단 없이 스크린 리더 알림)
- **에러 메시지:** `role="alert"` (크레딧 부족, 보고서 생성 실패)
- **인터뷰 스텝:** `aria-current="step"` (활성 스텝)
- **보고서 TOC:** `role="tablist"` / `role="tab"` (섹션 내비게이션)

### 5.3 키보드 내비게이션

- 인터뷰 위자드: Tab으로 폼 요소 이동, Enter로 진행, Escape로 뒤로
- 주소 후보 카드: 화살표 키 탐색, Enter 선택
- 목적 카드: 그리드 레이아웃 화살표 키, Enter 선택
- 보고서 TOC: Tab으로 링크 이동, Enter로 스크롤
- 모든 인터랙티브 요소에 가시적 포커스 인디케이터 (2px 링, 고대비)

### 5.4 색상 접근성

- 모든 텍스트 WCAG 2.1 AA (일반 텍스트 4.5:1, 대형 텍스트 3:1)
- 상태 뱃지: 색상 + 아이콘/텍스트 병용 (색상만으로 상태 전달하지 않음)
- 가격 변동: 빨간/파란 + 상승/하락 화살표 아이콘 병용

### 5.5 언어

- `<html lang="ko">` 루트 문서
- 날짜 포맷: `ko-KR` 로케일 (`2026년 4월 12일`)
- 숫자 포맷: 쉼표 구분 (`1,900원`, `3.5억`)
- 모든 폼 라벨, 에러 메시지, 플레이스홀더 한국어

---

## 6. 핵심 아키텍처 결정

### 6.1 토큰 저장 전략

Access token은 JavaScript 변수(React state/ref)에 저장 — `localStorage` 미사용 (XSS 방지).
Refresh token은 로컬 개발에서는 메모리 저장 (URL fragment에서 추출), 프로덕션에서는 httpOnly Secure cookie (Phase 5-3).
페이지 새로고침 시 `GET /auth/me`로 세션 복원 시도.

### 6.2 SSE 인증

네이티브 `EventSource` API는 커스텀 헤더를 보낼 수 없다.
**쿼리 파라미터 방식 채택:** `GET /reports/{id}/progress?token={accessToken}`
- 백엔드에서 쿼리 파라미터 `token` 검증 로직 추가 필요
- 서버 로그에서 URL 토큰 마스킹 필요 (보안)
- Access token은 15분 TTL이므로 노출 위험 제한적

### 6.3 인터뷰 상태 영속성

MVP에서 인터뷰 위자드 상태는 Zustand 메모리에만 존재.
페이지 이탈 시 상태 소실 (기존 Chainlit과 동일 동작).
향후 `sessionStorage` 영속화 고려.

### 6.4 보고서 마크다운 렌더링

보고서는 MinIO에 마크다운으로 저장. 차트 이미지 URL은 MinIO signed URL.
프론트엔드는 `react-markdown`으로 클라이언트 사이드 렌더링.
`NEXT_PUBLIC_STORAGE_URL` 환경변수 (docker-compose 설정 완료)가 이미지 베이스 URL.
