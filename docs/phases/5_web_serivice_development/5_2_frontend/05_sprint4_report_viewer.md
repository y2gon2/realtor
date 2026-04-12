# 05. Sprint 4 — 보고서 뷰어 + SSE 진행률 (5일)

> **목표:** 사용자가 `/reports/[id]`에서 보고서 생성 진행률을 SSE로 실시간 확인하고,
> 완료 시 7개 섹션과 차트가 포함된 마크다운 보고서를 열람한다.
>
> **선행 조건:** Sprint 3 완료, Backend Sprint 2 (보고서 CRUD + SSE)

---

## 1. 산출물

- `/reports/[id]` 페이지 (진행 중: SSE 프로그레스, 완료: 마크다운 뷰어)
- `hooks/useEventSource.ts` SSE 연결 훅
- `hooks/useReportProgress.ts` 보고서 진행률 훅
- `hooks/useScrollSpy.ts` TOC 활성 섹션 추적 훅
- `MarkdownRenderer.tsx` 커스텀 마크다운 렌더러

---

## 2. 보고서 상태 머신

`/reports/[id]` 페이지는 보고서 상태에 따라 다른 UI를 표시:

```
페이지 로드
    │
    ├─ GET /api/v1/reports/{id}
    │
    ├─ status = 'pending' | 'processing'
    │   └─ <ReportProgress> 렌더링
    │       └─ SSE 연결: GET /reports/{id}/progress?token={accessToken}
    │           ├─ 이벤트 수신 → 프로그레스 바 갱신
    │           ├─ step="완료" (percent=100) → SSE 종료 → 보고서 재조회
    │           └─ step="에러" → SSE 종료 → 에러 UI 표시
    │
    ├─ status = 'completed'
    │   └─ <ReportViewer> 렌더링
    │       └─ 마크다운 섹션 + 차트 이미지 + 사이드바 TOC
    │
    └─ status = 'failed'
        └─ <ReportError> 렌더링
            └─ 에러 메시지 + "다시 생성하기" 버튼
```

---

## 3. SSE 연결

### 3.1 `hooks/useEventSource.ts`

네이티브 `EventSource` API 사용. 인증은 쿼리 파라미터 토큰.

```typescript
import { useEffect, useRef, useCallback, useState } from 'react';
import { apiClient } from '@/lib/api-client';

interface UseEventSourceOptions<T> {
  url: string | null;           // null이면 연결 안 함
  onMessage: (data: T) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
}

interface UseEventSourceReturn {
  connected: boolean;
  close: () => void;
}

export function useEventSource<T>({
  url,
  onMessage,
  onError,
  onOpen,
}: UseEventSourceOptions<T>): UseEventSourceReturn {
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    if (!url) return;

    // 쿼리 파라미터에 토큰 추가
    const token = apiClient.getAccessToken();
    const separator = url.includes('?') ? '&' : '?';
    const fullUrl = token ? `${url}${separator}token=${token}` : url;

    const es = new EventSource(fullUrl);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      onOpen?.();
    };

    es.addEventListener('progress', (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as T;
        onMessage(data);
      } catch {
        // JSON 파싱 실패 무시
      }
    });

    es.onerror = (event) => {
      setConnected(false);
      onError?.(event);
      // EventSource는 자동 재연결 시도
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [url]);

  return { connected, close };
}
```

### 3.2 `hooks/useReportProgress.ts`

```typescript
import { useState, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEventSource } from './useEventSource';
import { apiClient } from '@/lib/api-client';
import type { Report, ProgressEvent } from '@/types/report';

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export function useReportProgress(reportId: string) {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 보고서 기본 정보 조회
  const reportQuery = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => apiClient.fetch<Report>(`/api/v1/reports/${reportId}`),
  });

  const report = reportQuery.data;
  const needsSSE = report && (report.status === 'pending' || report.status === 'processing');

  // SSE 이벤트 핸들러
  const handleMessage = useCallback((event: ProgressEvent) => {
    setProgress(event);

    if (event.percent === 100 || event.step === '완료') {
      setIsComplete(true);
      // 보고서 재조회 (완료된 데이터)
      queryClient.invalidateQueries({ queryKey: ['report', reportId] });
    }

    if (event.step === '에러') {
      setError(event.error ?? '보고서 생성 중 오류가 발생했습니다');
    }
  }, [reportId, queryClient]);

  // SSE 연결 (needsSSE가 true일 때만)
  const { connected, close } = useEventSource<ProgressEvent>({
    url: needsSSE ? `${API_URL}/api/v1/reports/${reportId}/progress` : null,
    onMessage: handleMessage,
  });

  return {
    report,
    progress,
    isComplete,
    error,
    connected,
    isLoading: reportQuery.isLoading,
    closeSSE: close,
  };
}
```

### 3.3 타입 정의

```typescript
// types/report.ts에 추가
export interface ProgressEvent {
  step: string;
  detail: string;
  percent: number;
  timestamp: string;
  markdown_url?: string;  // step="완료" 시
  error?: string;         // step="에러" 시
}
```

---

## 4. 진행률 UI

### 4.1 `report/ReportProgress.tsx`

```
┌─────────────────────────────────────────┐
│                                         │
│         보고서 생성 중...                 │
│    "마포래미안푸르지오 101동 1502호"       │
│                                         │
│    ████████████░░░░░░░░░░░░  45%        │  ← 애니메이션 프로그레스 바
│                                         │
│    ✅ 주소 정규화          완료            │
│    ✅ 데이터 수집          완료            │
│    ⏳ 차트 생성        생성 중...          │  ← 현재 스텝 (애니메이션)
│    ○ 세금/대출 계산       대기             │
│    ○ 보고서 생성          대기             │
│    ○ 요약 생성            대기             │
│    ○ 완료                 대기             │
│                                         │
│    예상 소요 시간: 약 60-90초              │
│                                         │
└─────────────────────────────────────────┘
```

### 4.2 `report/ProgressStepList.tsx`

7개 스텝을 순서대로 표시. 각 스텝의 상태:

| 상태 | 아이콘 | 색상 | 텍스트 |
|------|--------|------|--------|
| `completed` | ✅ CheckCircle | green | "완료" |
| `active` | ⏳ Loader2 (spin) | blue | detail 텍스트 |
| `pending` | ○ Circle | gray | "대기" |

**스텝 상태 판정 로직:**

```typescript
import { PROGRESS_STEPS } from '@/lib/constants';

function getStepStatus(
  stepIndex: number,
  currentProgress: ProgressEvent | null
): 'completed' | 'active' | 'pending' {
  if (!currentProgress) return stepIndex === 0 ? 'active' : 'pending';

  const stepThreshold = PROGRESS_STEPS[stepIndex].percent;
  const currentPercent = currentProgress.percent;

  if (currentPercent > stepThreshold) return 'completed';
  if (currentPercent >= (PROGRESS_STEPS[stepIndex - 1]?.percent ?? 0)
      && currentPercent <= stepThreshold) return 'active';
  return 'pending';
}
```

### 4.3 애니메이션

Framer Motion으로 각 스텝 상태 전환 애니메이션:

```tsx
<motion.div
  initial={{ opacity: 0.5 }}
  animate={{
    opacity: status === 'pending' ? 0.5 : 1,
    scale: status === 'active' ? 1.02 : 1,
  }}
  transition={{ duration: 0.3 }}
>
  {/* 스텝 내용 */}
</motion.div>
```

프로그레스 바:
```tsx
<motion.div
  className="h-2 bg-primary-500 rounded-full"
  initial={{ width: 0 }}
  animate={{ width: `${percent}%` }}
  transition={{ duration: 0.5, ease: 'easeOut' }}
/>
```

---

## 5. 보고서 뷰어

### 5.1 레이아웃

**데스크톱 (>= lg):**
```
┌───────────┬────────────────────────────────┐
│ TOC       │ 보고서 본문                      │
│ (sticky)  │                                │
│           │ [부동산 딥 리포트]                │
│ ● 입지분석 │  물건: 마포래미안푸르지오          │
│   가격분석 │  주소: 서울 마포구 마포대로 217    │
│   법률분석 │  분석목적: 매매_실거주             │
│   투자분석 │                                │
│   일조분석 │  ## 입지 분석                    │
│   리스크   │  ...마크다운 콘텐츠...            │
│   미래전망 │  [차트 이미지]                   │
│           │                                │
│           │  ## 가격/시세 분석               │
│           │  ...                            │
└───────────┴────────────────────────────────┘
     280px          나머지 (max-w-4xl)
```

**모바일 (< lg):**
```
┌─────────────────────────────────┐
│ [📋 목차]  ← Sheet 트리거 버튼    │
│                                 │
│ [부동산 딥 리포트]                │
│  물건: 마포래미안푸르지오          │
│                                 │
│  ## 입지 분석                    │
│  ...마크다운 콘텐츠...            │
│  [차트 이미지 (100% 너비)]       │
│                                 │
└─────────────────────────────────┘
```

### 5.2 `report/ReportViewer.tsx`

```tsx
'use client';

import { ReportSidebar } from './ReportSidebar';
import { ReportMobileTOC } from './ReportMobileTOC';
import { ReportSection } from './ReportSection';
import { ReportActions } from './ReportActions';
import { useScrollSpy } from '@/hooks/useScrollSpy';
import { SECTION_TITLES } from '@/lib/constants';
import type { Report } from '@/types/report';

interface ReportViewerProps {
  report: Report;
}

export function ReportViewer({ report }: ReportViewerProps) {
  const sectionIds = report.sections?.map(s => s.section_type) ?? [];
  const activeSection = useScrollSpy(sectionIds);

  return (
    <div className="flex">
      {/* 데스크톱 사이드바 */}
      <ReportSidebar
        sections={sectionIds}
        activeSection={activeSection}
        className="hidden lg:block w-[280px] sticky top-16 h-[calc(100vh-4rem)]"
      />

      <main className="flex-1 max-w-4xl px-4 md:px-6 py-8">
        {/* 모바일 TOC */}
        <ReportMobileTOC
          sections={sectionIds}
          activeSection={activeSection}
          className="lg:hidden mb-4"
        />

        {/* 보고서 헤더 */}
        <div className="mb-8">
          <h1 className="text-2xl md:text-3xl font-bold">부동산 딥 리포트</h1>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-sm text-gray-600">
            <dt className="font-medium">물건</dt>
            <dd>{report.normalized_address?.danji_name ?? report.address_input}</dd>
            <dt className="font-medium">주소</dt>
            <dd>{report.normalized_address?.road_address ?? ''}</dd>
            <dt className="font-medium">분석 목적</dt>
            <dd>{report.purpose}</dd>
            <dt className="font-medium">생성일</dt>
            <dd>{new Date(report.completed_at!).toLocaleDateString('ko-KR')}</dd>
          </dl>
          <ReportActions reportId={report.id} />
        </div>

        {/* 섹션 렌더링 */}
        {report.sections?.map(section => (
          <ReportSection
            key={section.section_type}
            id={section.section_type}
            title={SECTION_TITLES[section.section_type]}
            content={section.content}
          />
        ))}
      </main>
    </div>
  );
}
```

### 5.3 `report/MarkdownRenderer.tsx`

```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import type { Components } from 'react-markdown';

const components: Components = {
  // 헤딩에 앵커 ID 추가 (TOC 스크롤 대상)
  h2: ({ children, ...props }) => (
    <h2 className="text-xl font-bold mt-8 mb-4 scroll-mt-20" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="text-lg font-semibold mt-6 mb-3" {...props}>
      {children}
    </h3>
  ),

  // 이미지 (차트 — base64 PNG 또는 MinIO URL)
  img: ({ src, alt, ...props }) => (
    <figure className="my-6">
      <img
        src={src}
        alt={alt ?? '차트'}
        className="w-full max-w-2xl mx-auto rounded-lg shadow-sm"
        loading="lazy"
        {...props}
      />
      {alt && <figcaption className="text-center text-sm text-gray-500 mt-2">{alt}</figcaption>}
    </figure>
  ),

  // 테이블 (가로 스크롤 래퍼)
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-4">
      <table className="min-w-full border-collapse text-sm" {...props}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...props }) => (
    <th className="border-b-2 border-gray-200 px-3 py-2 text-left font-semibold bg-gray-50" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="border-b border-gray-100 px-3 py-2" {...props}>
      {children}
    </td>
  ),

  // 외부 링크
  a: ({ href, children, ...props }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary-600 hover:underline"
      {...props}
    >
      {children}
    </a>
  ),

  // 본문 텍스트 행간
  p: ({ children, ...props }) => (
    <p className="leading-relaxed mb-4" {...props}>{children}</p>
  ),
};

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
}
```

### 5.4 `hooks/useScrollSpy.ts`

```typescript
import { useState, useEffect } from 'react';

export function useScrollSpy(sectionIds: string[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: '-80px 0px -60% 0px' }
    );

    for (const id of sectionIds) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [sectionIds]);

  return activeId;
}
```

---

## 6. 보고서 액션

### 6.1 `report/ReportActions.tsx`

| 버튼 | 동작 |
|------|------|
| "인쇄/PDF" | `window.print()` + 인쇄용 CSS (`@media print`) |
| "Markdown 다운로드" | `GET /reports/{id}/markdown` → 302 → 파일 다운로드 |
| "삭제" | 확인 Dialog → `DELETE /reports/{id}` → `/dashboard` 이동 |

### 6.2 인쇄용 CSS

```css
@media print {
  /* 사이드바, 헤더, 푸터, 액션 버튼 숨김 */
  .report-sidebar, header, footer, .report-actions {
    display: none !important;
  }
  /* 본문 전체 너비 */
  main {
    max-width: 100% !important;
    padding: 0 !important;
  }
  /* 차트 이미지 페이지 분리 방지 */
  figure {
    break-inside: avoid;
  }
}
```

---

## 7. 백엔드 API 연동

| 엔드포인트 | 용도 | 사용처 |
|-----------|------|-------|
| `GET /api/v1/reports/{id}` | 보고서 상세 (상태 + 섹션) | useReportProgress, ReportViewer |
| `GET /api/v1/reports/{id}/progress?token=` | SSE 진행률 스트림 | useEventSource |
| `GET /api/v1/reports/{id}/markdown` | Markdown 다운로드 (302) | ReportActions |
| `DELETE /api/v1/reports/{id}` | 보고서 삭제 | ReportActions |

### SSE 이벤트 형식 (백엔드 계약, 04_sprint2_report_pipeline.md 섹션 2.2)

```
event: progress
data: {"step":"데이터 수집","detail":"실거래가 API 조회 중...","percent":30,"timestamp":"2026-04-08T10:00:30.123Z"}

event: progress
data: {"step":"완료","detail":"보고서 생성 완료 (45.2초)","percent":100,"markdown_url":"report-id/report.md","timestamp":"..."}

event: progress
data: {"step":"에러","detail":"...","percent":0,"error":"API 호출 실패","timestamp":"..."}
```

---

## 8. Sprint 4 검증 체크리스트

- [ ] `processing` 보고서 → SSE 프로그레스 바 실시간 업데이트
- [ ] 7단계 스텝 리스트: completed/active/pending 상태 정확
- [ ] `완료` 이벤트 수신 → SSE 종료 → ReportViewer로 자동 전환
- [ ] `에러` 이벤트 → 에러 UI + "다시 생성하기" 버튼
- [ ] ReportViewer: 7개 섹션 모두 마크다운 렌더링
- [ ] 차트 이미지 (MinIO URL 또는 base64) 정상 표시
- [ ] GFM 테이블 가로 스크롤 동작
- [ ] 데스크톱: 사이드바 TOC sticky + 스크롤 스파이 활성 표시
- [ ] 모바일: Sheet 컴포넌트 TOC + 접이식 동작
- [ ] "인쇄/PDF" → 브라우저 인쇄 대화 상자 (사이드바/헤더 숨김)
- [ ] "Markdown 다운로드" → 파일 다운로드 동작
- [ ] SSE 연결 끊김 → EventSource 자동 재연결
- [ ] 이미 `completed` 보고서 접근 시 → SSE 없이 바로 ReportViewer
- [ ] 모바일 (375px): 보고서 스크롤 가능, 차트 100% 너비
