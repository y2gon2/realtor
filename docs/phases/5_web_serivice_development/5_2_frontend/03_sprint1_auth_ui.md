# 03. Sprint 1 — 인증 UI (5일)

> **목표:** 사용자가 카카오/네이버/Google 소셜 로그인 또는 이메일/비밀번호로 가입·로그인하여
> 보호된 라우트(`/dashboard`, `/reports/*`, `/settings`)에 접근할 수 있다.
>
> **선행 조건:** Sprint 0 완료, Phase 5-1 Backend Sprint 1 (인증 시스템) 완료

---

## 1. 산출물

- `/login` 페이지 (소셜 로그인 3사 + 이메일/비밀번호)
- `/auth/callback` OAuth 콜백 핸들러
- `AuthProvider`, `useAuth` 훅
- `middleware.ts` 라우트 보호
- `lib/api-client.ts` 토큰 관리 + 401 자동 리프레시
- `lib/auth.ts` 토큰 저장/복원

---

## 2. 페이지

### 2.1 `/login` — 로그인 페이지

```
┌─────────────────────────────────┐
│        [로고] 부동산 AI          │
│                                 │
│    ┌──────────────────────┐    │
│    │  🟡 카카오로 로그인     │    │   ← bg: #FEE500, text: #000
│    └──────────────────────┘    │
│    ┌──────────────────────┐    │
│    │  🟢 네이버로 로그인     │    │   ← bg: #03C75A, text: #FFF
│    └──────────────────────┘    │
│    ┌──────────────────────┐    │
│    │  ⬜ Google로 로그인     │    │   ← bg: #FFF, border: #DADCE0
│    └──────────────────────┘    │
│                                 │
│    ─────── 또는 ───────         │
│                                 │
│    이메일  [____________]       │
│    비밀번호 [____________]       │
│    [  이메일로 로그인  ]         │
│                                 │
│    계정이 없으신가요? 회원가입    │
│                                 │
│    □ 이용약관 및 개인정보         │
│      처리방침에 동의합니다        │
└─────────────────────────────────┘
```

### 2.2 `/auth/callback` — OAuth 콜백

OAuth 제공자 인증 완료 후 백엔드가 리다이렉트하는 페이지.

**URL 형식 (백엔드 03_sprint1_auth.md 섹션 6.4):**
```
http://localhost:3000/auth/callback#access_token=...&refresh_token=...&return_to=/dashboard
```

> URL fragment(`#` 이후)는 서버로 전송되지 않으므로 보안상 안전.

---

## 3. 컴포넌트

### 3.1 `components/auth/SocialLoginButtons.tsx`

```tsx
'use client';

const API_URL = process.env.NEXT_PUBLIC_API_URL;

function handleSocialLogin(provider: 'kakao' | 'naver' | 'google') {
  const returnTo = new URLSearchParams(window.location.search).get('return_to') || '/dashboard';
  window.location.href = `${API_URL}/api/v1/auth/oauth/${provider}/authorize?return_to=${encodeURIComponent(returnTo)}`;
}
```

각 버튼 스타일:

| 프로바이더 | 배경색 | 텍스트색 | 아이콘 | 라벨 |
|-----------|--------|---------|--------|------|
| 카카오 | `#FEE500` | `#000000` | kakao-logo.svg | "카카오로 로그인" |
| 네이버 | `#03C75A` | `#FFFFFF` | naver-logo.svg | "네이버로 로그인" |
| Google | `#FFFFFF` (border: `#DADCE0`) | `#374151` | google-logo.svg | "Google로 로그인" |

### 3.2 `components/auth/EmailLoginForm.tsx`

`react-hook-form` + `zod` 기반:

```typescript
const loginSchema = z.object({
  email: z.string().email('이메일 형식이 올바르지 않습니다'),
  password: z.string().min(8, '비밀번호는 8자 이상이어야 합니다'),
});
```

**제출 시:**
1. `POST /api/v1/auth/login` 호출
2. 성공: `access_token`, `refresh_token` 수신 → `apiClient.setTokens()` → `/dashboard` 이동
3. 실패:
   - `invalid_credentials` → "이메일 또는 비밀번호가 올바르지 않습니다"
   - `account_locked` → "계정이 잠겼습니다. {locked_until} 이후 다시 시도해주세요"

### 3.3 `components/auth/SignupForm.tsx`

```typescript
const signupSchema = z.object({
  email: z.string().email('이메일 형식이 올바르지 않습니다'),
  password: z.string().min(8, '비밀번호는 8자 이상이어야 합니다'),
  name: z.string().min(1, '이름을 입력해주세요').max(100),
  marketing_consent: z.boolean().default(false),
});
```

**제출 시:** `POST /api/v1/auth/signup` → 성공: 자동 로그인 + `/dashboard` 이동

### 3.4 `components/auth/ConsentCheckbox.tsx`

- 이용약관 및 개인정보처리방침 링크 (별도 정적 페이지)
- 체크박스 선택 필수 (소셜 로그인 시에도)

---

## 4. 인증 플로우

### 4.1 소셜 로그인 전체 흐름

```
[프론트엔드]                    [Go API]                     [OAuth 제공자]
    │                              │                              │
    ├─ 카카오 버튼 클릭             │                              │
    │  window.location.href =      │                              │
    │  /api/v1/auth/oauth/         │                              │
    │  kakao/authorize?            │                              │
    │  return_to=/dashboard        │                              │
    │ ─────────────────────────►   │                              │
    │                              ├─ state 생성, Redis 저장       │
    │                              ├─ 302 → kauth.kakao.com ──►   │
    │                              │                              │
    │                              │          사용자 카카오 로그인  │
    │                              │                              │
    │                              │  ◄── callback?code=...&state=│
    │                              ├─ state 검증                   │
    │                              ├─ code → access_token 교환     │
    │                              ├─ 프로필 조회                   │
    │                              ├─ users 검색/생성               │
    │                              ├─ JWT 발급                     │
    │                              │                              │
    │  ◄─ 302 localhost:3000/      │                              │
    │      auth/callback#          │                              │
    │      access_token=...&       │                              │
    │      refresh_token=...&      │                              │
    │      return_to=/dashboard    │                              │
    │                              │                              │
    ├─ AuthCallbackHandler         │                              │
    │  URL fragment 파싱            │                              │
    │  apiClient.setTokens()       │                              │
    │  router.push(return_to)      │                              │
```

### 4.2 이메일 로그인 흐름

```
[프론트엔드]                    [Go API]
    │                              │
    ├─ POST /auth/login            │
    │  { email, password }  ──────►│
    │                              ├─ bcrypt 검증
    │                              ├─ JWT 발급
    │  ◄── 200 {                   │
    │    access_token,             │
    │    refresh_token,            │
    │    user: { ... }             │
    │  }                           │
    │                              │
    ├─ apiClient.setTokens()       │
    │  authContext.setUser(user)    │
    │  router.push('/dashboard')   │
```

### 4.3 토큰 리프레시 흐름

```
[API 클라이언트]                [Go API]
    │                              │
    ├─ GET /reports (401) ────────►│ ← access token 만료
    │                              │
    ├─ POST /auth/refresh          │
    │  { refresh_token }  ────────►│
    │                              ├─ 기존 세션 revoke
    │                              ├─ 신규 토큰 발급
    │  ◄── 200 {                   │
    │    access_token,             │
    │    refresh_token             │
    │  }                           │
    │                              │
    ├─ 토큰 갱신                    │
    ├─ 원래 요청 재시도 ───────────►│
    │  ◄── 200 { reports: [...] }  │
```

---

## 5. 훅 & 프로바이더

### 5.1 `providers/AuthProvider.tsx`

```tsx
'use client';

import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';
import type { User } from '@/types/auth';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string, user: User) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // 페이지 로드 시 세션 복원 시도
  useEffect(() => {
    const restore = async () => {
      try {
        const data = await apiClient.fetch<{ user: User }>('/api/v1/auth/me');
        setUser(data.user);
      } catch {
        // 토큰 없거나 만료 → 미인증 상태
        apiClient.clearTokens();
      } finally {
        setIsLoading(false);
      }
    };
    restore();
  }, []);

  const login = useCallback((accessToken: string, refreshToken: string, user: User) => {
    apiClient.setTokens(accessToken, refreshToken);
    setUser(user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiClient.fetch('/api/v1/auth/logout', { method: 'POST' });
    } catch {
      // 로그아웃 실패해도 클라이언트 상태는 정리
    }
    apiClient.clearTokens();
    setUser(null);
    window.location.href = '/login';
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      isLoading,
      isAuthenticated: !!user,
      login,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

### 5.2 `auth/callback/page.tsx`

```tsx
'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { apiClient } from '@/lib/api-client';

export default function AuthCallbackPage() {
  const router = useRouter();
  const { login } = useAuth();

  useEffect(() => {
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);

    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const returnTo = params.get('return_to') || '/dashboard';

    if (!accessToken || !refreshToken) {
      router.push('/login?error=auth_failed');
      return;
    }

    // 토큰 설정 후 사용자 정보 조회
    apiClient.setTokens(accessToken, refreshToken);
    apiClient.fetch<{ user: User }>('/api/v1/auth/me')
      .then(data => {
        login(accessToken, refreshToken, data.user);
        router.push(returnTo);
      })
      .catch(() => {
        router.push('/login?error=auth_failed');
      });
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-gray-500">로그인 처리 중...</p>
    </div>
  );
}
```

---

## 6. 라우트 보호

### 6.1 `middleware.ts`

```typescript
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const protectedRoutes = ['/dashboard', '/reports', '/settings'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 보호된 라우트인지 확인
  const isProtected = protectedRoutes.some(route => pathname.startsWith(route));
  if (!isProtected) return NextResponse.next();

  // 미들웨어에서는 클라이언트 토큰 접근 불가 (메모리 저장이므로)
  // → (protected)/layout.tsx의 AuthGuard 컴포넌트에서 클라이언트 사이드 검증
  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/reports/:path*', '/settings/:path*'],
};
```

> **참고:** Access token이 메모리에 저장되므로 서버 사이드 미들웨어에서 검증 불가.
> 실제 라우트 보호는 `(protected)/layout.tsx`의 `AuthGuard`가 클라이언트 사이드에서 수행.

### 6.2 `(protected)/layout.tsx`

```tsx
'use client';

import { useAuth } from '@/hooks/useAuth';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push(`/login?return_to=${window.location.pathname}`);
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-primary-500" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return <>{children}</>;
}
```

---

## 7. Header 컴포넌트

### 7.1 `components/layout/Header.tsx`

인증 상태에 따라 다른 UI 표시:

| 상태 | 오른쪽 표시 |
|------|-----------|
| 미인증 | "로그인" 버튼 |
| 인증됨 | 사용자 이름 + 드롭다운 (대시보드, 설정, 로그아웃) |

모바일(< md): 햄버거 메뉴 → Sheet 슬라이드아웃

---

## 8. 백엔드 API 연동 명세

### 8.1 연동 엔드포인트

| 엔드포인트 | 용도 | 프론트엔드 사용처 |
|-----------|------|----------------|
| `POST /api/v1/auth/signup` | 이메일 가입 | SignupForm.tsx |
| `POST /api/v1/auth/login` | 이메일 로그인 | EmailLoginForm.tsx |
| `GET /api/v1/auth/oauth/{provider}/authorize` | OAuth 시작 | SocialLoginButtons.tsx (window.location.href) |
| `GET /api/v1/auth/oauth/{provider}/callback` | OAuth 콜백 | 백엔드 → /auth/callback 리다이렉트 (프론트엔드 직접 호출 안 함) |
| `POST /api/v1/auth/refresh` | 토큰 갱신 | api-client.ts (자동) |
| `POST /api/v1/auth/logout` | 로그아웃 | AuthProvider.logout() |
| `GET /api/v1/auth/me` | 현재 사용자 | AuthProvider (마운트 시 세션 복원) |

### 8.2 타입 정의 (`types/auth.ts`)

```typescript
export interface User {
  id: string;
  email: string;
  name: string;
  tier: 'free' | 'basic' | 'pro';
  credits_remaining: number;
  auth_provider: 'email' | 'kakao' | 'naver' | 'google';
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  name: string;
  marketing_consent: boolean;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
}
```

---

## 9. Sprint 1 검증 체크리스트

- [ ] 이메일 가입 → 자동 로그인 → `/dashboard` 접근 가능
- [ ] 이메일 로그인 → 성공 → `/dashboard` 이동
- [ ] 잘못된 비밀번호 → "이메일 또는 비밀번호가 올바르지 않습니다" 에러 표시
- [ ] 카카오 소셜 로그인 → 카카오 인증 → `/auth/callback` → `/dashboard`
- [ ] 네이버 소셜 로그인 → 네이버 인증 → `/auth/callback` → `/dashboard`
- [ ] Google 소셜 로그인 → Google 인증 → `/auth/callback` → `/dashboard`
- [ ] 비인증 상태에서 `/dashboard` 접근 → `/login` 리다이렉트
- [ ] 토큰 리프레시: access token 만료 후 API 호출 → 자동 갱신 → 요청 성공
- [ ] 로그아웃 → 클라이언트 토큰 삭제 → `/login` 이동 → `/dashboard` 접근 불가
- [ ] 모바일 (375px): 로그인 폼 사용 가능, 소셜 버튼 터치 타겟 44px+
- [ ] 소셜 로그인 버튼 브랜드 색상 정확 (카카오 #FEE500, 네이버 #03C75A)
- [ ] 이용약관/개인정보처리방침 체크박스 필수
