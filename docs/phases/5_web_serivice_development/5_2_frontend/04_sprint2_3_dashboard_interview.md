# 04. Sprint 2-3 — 대시보드 + 인터뷰 위자드 (9-10일)

> **Sprint 2 (4일):** 대시보드에서 보고서 목록, 사용량 통계, 크레딧 잔액을 확인한다.
> **Sprint 3 (5-6일):** 4단계 인터뷰 위자드로 보고서 생성을 요청한다.
>
> **선행 조건:** Sprint 1 완료, Backend Sprint 2 (보고서 CRUD) + Sprint 3 (주소/사용자)

---

## Sprint 2 — 대시보드

### 1. 산출물

- `/dashboard` 페이지
- `ReportList`, `ReportCard`, `UsageStats`, `StatusFilter`, `EmptyState` 컴포넌트
- `queries/reports.ts`, `queries/user.ts` TanStack Query 훅
- `types/report.ts`, `types/user.ts` 타입 정의

---

### 2. `/dashboard` 페이지 구조

```
┌─────────────────────────────────────────────────┐
│  [Header: 로고  |  대시보드  설정  |  홍길동 ▼]  │
├─────────────────────────────────────────────────┤
│                                                 │
│  내 보고서                    [+ 새 보고서 생성]  │
│                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 잔여 크레딧│ │ 생성된     │ │ 이번 달    │        │
│  │    1건    │ │ 보고서 3건 │ │  1건      │        │
│  └──────────┘ └──────────┘ └──────────┘        │
│                                                 │
│  상태: [전체] [완료] [생성중] [실패]               │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ 마포래미안푸르지오        매매_실거주        │    │
│  │ 2026-04-10 14:30          [완료] ●       │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │ 강남역삼 개나리아파트      매매_투자        │    │
│  │ 2026-04-09 10:15          [생성중] ◌     │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  [더 보기]                                       │
└─────────────────────────────────────────────────┘
```

### 3. 컴포넌트

#### 3.1 `dashboard/ReportList.tsx`

TanStack Query `useInfiniteQuery` 기반 커서 페이지네이션:

```typescript
// queries/reports.ts
export function useReports(statusFilter?: string) {
  return useInfiniteQuery({
    queryKey: ['reports', statusFilter],
    queryFn: ({ pageParam }) =>
      apiClient.fetch<ReportListResponse>(
        `/api/v1/reports?${new URLSearchParams({
          ...(statusFilter && { status: statusFilter }),
          ...(pageParam && { cursor: pageParam }),
          limit: '20',
        })}`
      ),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    initialPageParam: undefined as string | undefined,
  });
}
```

#### 3.2 `dashboard/ReportCard.tsx`

| 필드 | 표시 |
|------|------|
| `address_input` | 주소 (굵게) |
| `purpose` | 목적 라벨 |
| `status` | 뱃지 (색상+아이콘) |
| `created_at` | 날짜 (ko-KR 포맷) |
| `progress_percent` | 생성 중일 때 퍼센트 표시 |

**클릭 동작:**
- `completed` → `/reports/[id]` (뷰어)
- `processing` → `/reports/[id]` (진행률)
- `failed` → 에러 표시 + 재시도 옵션

**삭제:** 점 3개 메뉴 → "삭제" → 확인 Dialog → `DELETE /api/v1/reports/{id}`

#### 3.3 `dashboard/UsageStats.tsx`

`GET /api/v1/user/usage` 응답 표시:
- 잔여 크레딧: `credits_remaining`
- 생성된 보고서: `current_month.reports_generated`
- 이번 달: `current_month.reports_completed`

#### 3.4 `dashboard/EmptyState.tsx`

보고서가 0건일 때:
```
"아직 생성된 보고서가 없습니다"
"주소를 입력하면 AI가 부동산을 분석해드립니다"
[새 보고서 생성하기 →]
```

### 4. 타입 정의

```typescript
// types/report.ts
export interface Report {
  id: string;
  address_input: string;
  normalized_address?: NormalizedAddress;
  purpose: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress_percent: number;
  current_step?: string;
  sections?: ReportSection[];
  markdown_url?: string;
  generation_time_ms?: number;
  created_at: string;
  completed_at?: string;
}

export interface ReportSection {
  section_type: string;
  content: string;
}

export interface ReportListResponse {
  reports: Report[];
  next_cursor?: string;
}

// types/user.ts
export interface UsageStats {
  tier: string;
  credits_remaining: number;
  credits_total_purchased: number;
  current_month: {
    reports_generated: number;
    reports_completed: number;
    reports_failed: number;
  };
}
```

### 5. 백엔드 API 연동

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /api/v1/reports?status=&limit=20&cursor=` | 보고서 목록 |
| `DELETE /api/v1/reports/{id}` | 보고서 삭제 |
| `GET /api/v1/user/usage` | 사용량 통계 |
| `GET /api/v1/user/profile` | 사용자 프로필 (Header 표시) |

### 6. Sprint 2 검증 체크리스트

- [ ] 보고서 목록 로드 (최소 1건)
- [ ] 상태 뱃지 정확한 색상/아이콘
- [ ] "더 보기" 버튼 → 다음 페이지 로드
- [ ] 상태 필터 동작 (완료만, 실패만 등)
- [ ] 빈 상태 → "새 보고서 생성하기" CTA 표시
- [ ] 보고서 삭제 → 확인 Dialog → 목록에서 제거
- [ ] 사용량 통계 카드 정확한 값 표시
- [ ] 모바일 (375px): 단일 컬럼, 터치 친화적

---

## Sprint 3 — 인터뷰 위자드

### 7. 산출물

- `/reports/new` 페이지
- `InterviewWizard`, `StepAddressInput`, `StepAddressConfirm`, `StepPurposeSelect`, `StepSummary` 컴포넌트
- `stores/interview-store.ts` Zustand 스토어
- `queries/address.ts` 주소 검색 훅

---

### 8. 인터뷰 상태 관리

#### 8.1 `stores/interview-store.ts`

```typescript
import { create } from 'zustand';
import type { AddressCandidate } from '@/types/address';

interface InterviewState {
  step: 1 | 2 | 3 | 4;
  addressInput: string;
  candidates: AddressCandidate[];
  selectedCandidate: AddressCandidate | null;
  purpose: string;
  customNotes: string;

  // 액션
  setStep: (step: 1 | 2 | 3 | 4) => void;
  setAddressInput: (input: string) => void;
  setCandidates: (candidates: AddressCandidate[]) => void;
  selectCandidate: (candidate: AddressCandidate) => void;
  setPurpose: (purpose: string) => void;
  setCustomNotes: (notes: string) => void;
  reset: () => void;
}

const initialState = {
  step: 1 as const,
  addressInput: '',
  candidates: [],
  selectedCandidate: null,
  purpose: '',
  customNotes: '',
};

export const useInterviewStore = create<InterviewState>((set) => ({
  ...initialState,
  setStep: (step) => set({ step }),
  setAddressInput: (addressInput) => set({ addressInput }),
  setCandidates: (candidates) => set({ candidates }),
  selectCandidate: (selectedCandidate) => set({ selectedCandidate }),
  setPurpose: (purpose) => set({ purpose }),
  setCustomNotes: (customNotes) => set({ customNotes }),
  reset: () => set(initialState),
}));
```

#### 8.2 타입 정의 (`types/address.ts`)

```typescript
export interface AddressCandidate {
  place_name: string;
  address_name: string;       // 지번 주소
  road_address: string;       // 도로명 주소
  category: string;           // "부동산 > 아파트"
  lat: number;
  lng: number;
  kakao_id: string;
}

export interface ResolveResponse {
  candidates: AddressCandidate[];
}
```

---

### 9. 4단계 위자드 상세

#### 9.1 Step 1: 주소 입력 (`StepAddressInput.tsx`)

**UI:**
```
"분석할 부동산의 주소를 입력해주세요"
"아파트 단지명, 도로명/지번 주소 모두 가능합니다"

  [마포래미안푸르지오 101동 1502호   ]   ← 큰 텍스트 입력
  
  예시:
  [마포래미안푸르지오 101동] [강남구 역삼동 123-4] [잠실엘스]

  [다음 →]
```

**동작:**
1. 텍스트 입력 (autoFocus)
2. "다음" 클릭 또는 Enter 시 `POST /api/v1/address/resolve` 호출
3. 로딩 상태 표시
4. 후보 0건 → 에러 메시지: "주소를 찾을 수 없습니다. 다시 입력해주세요"
5. 후보 1건 이상 → Step 2로 이동

**API 연동:**
```typescript
// queries/address.ts
export function useResolveAddress() {
  return useMutation({
    mutationFn: (query: string) =>
      apiClient.fetch<ResolveResponse>('/api/v1/address/resolve', {
        method: 'POST',
        body: JSON.stringify({ query }),
      }),
  });
}
```

> **참고:** `POST /api/v1/address/resolve`는 인증 옵션 (비로그인도 호출 가능, 백엔드 05_sprint3 섹션 2.1).
> 단, `/reports/new`는 보호된 라우트이므로 실제로는 항상 인증된 상태.

#### 9.2 Step 2: 주소 확인 (`StepAddressConfirm.tsx`)

**UI:**
```
"다음 중 분석할 주소를 선택해주세요"

  ┌─────────────────────────────────────┐
  │ ○ 마포래미안푸르지오                   │  ← 라디오 카드
  │   지번: 서울 마포구 아현동 699          │
  │   도로명: 서울 마포구 마포대로 217       │
  │   카테고리: 부동산 > 아파트              │
  └─────────────────────────────────────┘
  ┌─────────────────────────────────────┐
  │ ○ 마포푸르지오시티                     │
  │   지번: 서울 마포구 공덕동 256          │
  │   도로명: 서울 마포구 마포대로 194       │
  └─────────────────────────────────────┘

  [← 다시 입력]                   [다음 →]
```

**동작:**
- 후보 최대 4건 표시 (백엔드 정규화)
- 라디오 버튼으로 1건 선택
- "다시 입력" → Step 1로 복귀
- 선택 없이 "다음" 불가 (버튼 비활성)
- interview.py 라인 84-163 로직 참조

#### 9.3 Step 3: 목적 선택 (`StepPurposeSelect.tsx`)

**UI:**
```
"어떤 목적으로 분석하시나요?"

  ┌──────────────┐  ┌──────────────┐
  │ 🏠 매매       │  │ 📈 매매       │
  │ 구매 (실거주)  │  │ 구매 (투자)   │
  └──────────────┘  └──────────────┘
  ┌──────────────┐  ┌──────────────┐
  │ 💰 매매       │  │ 🔑 전세/월세   │
  │ 매도          │  │ (세입 검토)   │
  └──────────────┘  └──────────────┘
  ┌──────────────┐  ┌──────────────┐
  │ ⚖️ 경매/공매  │  │ ✏️ 기타       │
  │ 입찰 검토     │  │ (직접 입력)   │
  └──────────────┘  └──────────────┘

  "기타" 선택 시:
  [분석 목적을 직접 입력해주세요           ]

  [← 이전]                      [다음 →]
```

**동작:**
- 2x3 그리드 카드 (모바일에서도 2열 유지)
- 선택 시 테두리 하이라이트 (primary 색상)
- "기타" 선택 → 텍스트 입력 필드 표시
- interview.py 라인 169-176의 6개 선택지 정확히 매칭

#### 9.4 Step 4: 확인 (`StepSummary.tsx`)

**UI:**
```
"다음 조건으로 보고서를 생성합니다"

  ┌───────────────────────────────┐
  │  물건     마포래미안푸르지오      │
  │  주소     서울 마포구 마포대로 217│
  │  분석목적  매매 — 구매 (실거주)   │
  │  기본조건  1주택 기준 세금/대출   │
  └───────────────────────────────┘

  [크레딧 1건 차감]  잔여: 1건

  [← 조건 수정]          [🚀 보고서 생성 시작]
```

**동작:**
1. "조건 수정" → Step 1로 복귀 (interview.py의 재귀 호출과 동일)
2. "보고서 생성 시작" 클릭:
   - 크레딧 부족 시 → "크레딧이 부족합니다. 충전하시겠습니까?" + `/settings` 링크
   - 충분 시 → `POST /api/v1/reports` 호출

**POST /api/v1/reports 페이로드:**

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

**응답 202:**
```json
{
  "report_id": "uuid",
  "job_id": "1712574000000-0",
  "status": "pending",
  "progress_url": "/api/v1/reports/{id}/progress",
  "credits_remaining": 0
}
```

3. 성공 → `interviewStore.reset()` → `router.push(/reports/${report_id})`

---

### 10. 애니메이션

Framer Motion `AnimatePresence` + `motion.div`로 스텝 전환:

```tsx
<AnimatePresence mode="wait">
  <motion.div
    key={step}
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
    transition={{ duration: 0.2 }}
  >
    {/* 현재 스텝 컴포넌트 */}
  </motion.div>
</AnimatePresence>
```

---

### 11. 백엔드 API 연동 (Sprint 3)

| 엔드포인트 | 용도 | 사용처 |
|-----------|------|-------|
| `POST /api/v1/address/resolve` | 주소 검색 | StepAddressInput → Step 2 전환 |
| `POST /api/v1/reports` | 보고서 생성 | StepSummary → `/reports/[id]` 이동 |

### 12. Sprint 3 검증 체크리스트

- [ ] Step 1: "마포래미안푸르지오" 입력 → 후보 1건 이상 반환
- [ ] Step 1: 잘못된 주소 → "주소를 찾을 수 없습니다" 에러
- [ ] Step 2: 후보 카드 선택 가능, "다시 입력" 동작
- [ ] Step 3: 6개 목적 카드 정확한 라벨
- [ ] Step 3: "기타" 선택 → 텍스트 입력 필드 표시
- [ ] Step 4: 선택 요약 정확, "조건 수정" → Step 1 복귀
- [ ] Step 4: 크레딧 부족 → 에러 메시지 + 충전 링크
- [ ] Step 4: "보고서 생성 시작" → 202 응답 → `/reports/[id]` 이동
- [ ] 스텝 전환 애니메이션 부드러움
- [ ] StepIndicator 현재 스텝 정확히 표시
- [ ] 모바일 (375px): 모든 스텝 사용 가능, 카드 터치 타겟 44px+
- [ ] 뒤로 가기 버튼(브라우저) 시 이전 스텝으로 이동 (URL 쿼리 파라미터 `?step=N` 동기화)
