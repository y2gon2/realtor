# 02. Sprint 0 — 프로젝트 스캐폴드 (1일)

> **목표:** `docker compose up frontend`로 Next.js 개발 서버가 `http://localhost:3000`에서
> 핫 리로드와 함께 동작한다.
>
> **선행 조건:** Phase 5-0 Docker Compose 환경 구축 완료

---

## 1. 산출물

- `codes/realtor-ai-frontend/` 프로젝트 전체 골격
- `package.json` + 모든 핵심 의존성
- Tailwind CSS v4, ESLint, Vitest 설정
- Docker Compose 연동 (.env의 `FRONTEND_SRC_PATH` 설정)
- 플레이스홀더 랜딩 페이지
- 프로덕션 Dockerfile (멀티스테이지)

---

## 2. 프로젝트 초기화

### 2.1 create-next-app

```bash
cd /home/gon/ws/rag/codes
npx create-next-app@latest realtor-ai-frontend \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir \
  --import-alias "@/*" \
  --turbopack
```

### 2.2 핵심 의존성 설치

```bash
cd /home/gon/ws/rag/codes/realtor-ai-frontend

# 상태 관리 & 데이터 페칭
npm install @tanstack/react-query zustand

# 폼 & 검증
npm install react-hook-form zod @hookform/resolvers

# UI 프리미티브 (shadcn/ui 초기화)
npx shadcn@latest init
npx shadcn@latest add button card input badge progress dialog sheet tabs table skeleton textarea

# 추가 UI
npm install lucide-react sonner framer-motion

# 마크다운
npm install react-markdown remark-gfm rehype-raw

# 결제 (Sprint 6에서 사용, 미리 설치)
npm install @tosspayments/tosspayments-sdk

# 유틸리티
npm install clsx tailwind-merge

# 개발 의존성
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
npm install -D @tanstack/react-query-devtools
npm install -D @playwright/test
```

---

## 3. 설정 파일

### 3.1 `next.config.ts`

```typescript
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',  // 프로덕션 Docker 빌드용
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: 'localhost',
        port: '9000',           // MinIO
        pathname: '/realtor-reports/**',
      },
    ],
  },
};

export default nextConfig;
```

### 3.2 `tailwind.config.ts`

```typescript
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Pretendard Variable',
          'Pretendard',
          '-apple-system',
          'BlinkMacSystemFont',
          'system-ui',
          'sans-serif',
        ],
      },
      colors: {
        kakao: '#FEE500',
        naver: '#03C75A',
      },
    },
  },
  plugins: [],
};

export default config;
```

### 3.3 `vitest.config.ts`

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
```

### 3.4 `tests/setup.ts`

```typescript
import '@testing-library/jest-dom/vitest';
```

### 3.5 `.env.local`

```bash
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_STORAGE_URL=http://localhost:9000
```

### 3.6 `.env.example`

```bash
# Go API 서버
NEXT_PUBLIC_API_URL=http://localhost:8080

# MinIO 스토리지 (보고서 차트 이미지)
NEXT_PUBLIC_STORAGE_URL=http://localhost:9000
```

---

## 4. 루트 레이아웃

### 4.1 `src/app/layout.tsx`

```tsx
import type { Metadata } from 'next';
import localFont from 'next/font/local';
import { QueryProvider } from '@/providers/QueryProvider';
import { AuthProvider } from '@/providers/AuthProvider';
import { Toaster } from 'sonner';
import './globals.css';

const pretendard = localFont({
  src: '../../public/fonts/PretendardVariable.woff2',
  display: 'swap',
  variable: '--font-pretendard',
});

export const metadata: Metadata = {
  title: '부동산 AI 어드바이저',
  description: '주소만 입력하면 시세, 입지, 세금, 투자 수익률까지 — AI 부동산 분석 보고서',
  openGraph: {
    title: '부동산 AI 어드바이저',
    description: 'AI가 분석하는 부동산 종합 보고서',
    locale: 'ko_KR',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={pretendard.variable}>
      <body className="font-sans antialiased">
        <QueryProvider>
          <AuthProvider>
            {children}
            <Toaster position="top-center" richColors />
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
```

### 4.2 `src/providers/QueryProvider.tsx`

```tsx
'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,       // 1분
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  }));

  return (
    <QueryClientProvider client={client}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
```

### 4.3 `src/app/page.tsx` (플레이스홀더)

```tsx
export default function LandingPage() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">부동산 AI 어드바이저</h1>
        <p className="mt-4 text-gray-500">서비스 준비 중...</p>
      </div>
    </main>
  );
}
```

---

## 5. Docker Compose 연동

### 5.1 `.env` 업데이트

`codes/local-infra/.env`에 추가:

```bash
FRONTEND_SRC_PATH=/home/gon/ws/rag/codes/realtor-ai-frontend
```

### 5.2 시작 확인

```bash
cd /home/gon/ws/rag/codes/local-infra

# 프론트엔드만 시작 (인프라 서비스는 이미 실행 중이라고 가정)
docker compose up -d frontend

# 로그 확인
docker compose logs -f frontend

# 기대 출력:
#  ▲ Next.js 15.x
#  - Local:    http://localhost:3000
#  - Turbopack ready
```

### 5.3 핫 리로드 테스트

호스트에서 `src/app/page.tsx`의 텍스트를 수정 → 브라우저 자동 갱신 확인.
만약 갱신되지 않으면 docker-compose.yml의 frontend environment에 `WATCHPACK_POLLING: "true"` 추가.

---

## 6. 프로덕션 Dockerfile

```dockerfile
# Stage 1: 의존성
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Stage 2: 빌드
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 3: 실행 (standalone)
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
```

---

## 7. 유틸리티 초기 설정

### 7.1 `src/lib/cn.ts`

```typescript
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

### 7.2 `src/lib/constants.ts`

```typescript
// 분석 목적 선택지 (interview.py:169 기반)
export const PURPOSE_CHOICES = [
  { value: '매매_실거주', label: '매매 — 구매 (실거주)', icon: 'Home' },
  { value: '매매_투자', label: '매매 — 구매 (투자/임대)', icon: 'TrendingUp' },
  { value: '매도', label: '매매 — 매도 (매각 시점/가격 판단)', icon: 'DollarSign' },
  { value: '전세', label: '전세/월세 (세입 검토)', icon: 'Key' },
  { value: '경매', label: '경매/공매 입찰 검토', icon: 'Gavel' },
  { value: '기타', label: '기타 (직접 입력)', icon: 'MoreHorizontal' },
] as const;

// SSE 진행률 스텝 (progress.py STEP_PERCENT 기반)
export const PROGRESS_STEPS = [
  { step: '주소 정규화', percent: 10, icon: 'MapPin' },
  { step: '데이터 수집', percent: 30, icon: 'Database' },
  { step: '차트 생성', percent: 45, icon: 'BarChart' },
  { step: '세금/대출 계산', percent: 50, icon: 'Calculator' },
  { step: '보고서 생성', percent: 75, icon: 'Brain' },
  { step: '요약 생성', percent: 90, icon: 'FileText' },
  { step: '완료', percent: 100, icon: 'CheckCircle' },
] as const;

// 보고서 섹션 타입 → 한국어 제목
export const SECTION_TITLES: Record<string, string> = {
  location: '입지 분석',
  price: '가격/시세 분석',
  legal: '법률/규제 분석',
  investment: '투자 수익률 분석',
  sunview: '일조/조망 분석',
  risk: '리스크 분석',
  future: '미래 전망',
};

// 보고서 상태 → 한국어 + 뱃지 variant
export const STATUS_CONFIG: Record<string, { label: string; variant: string }> = {
  pending: { label: '대기 중', variant: 'secondary' },
  processing: { label: '생성 중', variant: 'default' },
  completed: { label: '완료', variant: 'success' },
  failed: { label: '실패', variant: 'destructive' },
};
```

---

## 8. 첫 테스트

### 8.1 `tests/unit/constants.test.ts`

```typescript
import { describe, it, expect } from 'vitest';
import { PURPOSE_CHOICES, PROGRESS_STEPS, SECTION_TITLES } from '@/lib/constants';

describe('constants', () => {
  it('has 6 purpose choices', () => {
    expect(PURPOSE_CHOICES).toHaveLength(6);
  });

  it('progress steps end at 100%', () => {
    const last = PROGRESS_STEPS[PROGRESS_STEPS.length - 1];
    expect(last.percent).toBe(100);
    expect(last.step).toBe('완료');
  });

  it('has 7 section titles', () => {
    expect(Object.keys(SECTION_TITLES)).toHaveLength(7);
  });
});
```

---

## 9. Sprint 0 검증 체크리스트

- [ ] `codes/realtor-ai-frontend/` 디렉토리 생성 + `package.json` 존재
- [ ] `docker compose up frontend` 에러 없이 시작
- [ ] `http://localhost:3000` 플레이스홀더 페이지 렌더링
- [ ] 호스트에서 파일 수정 → 브라우저 핫 리로드 동작
- [ ] `npm run build` 성공 (TypeScript 에러 없음)
- [ ] `npm run lint` 통과
- [ ] `npm run test` (vitest) — constants 테스트 통과
- [ ] `<html lang="ko">` 확인 (페이지 소스 보기)
- [ ] Pretendard 폰트 로드 확인 (브라우저 네트워크 탭)
