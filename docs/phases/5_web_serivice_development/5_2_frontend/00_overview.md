# Phase 5-2 Frontend Development — 전체 개요

> **최종 업데이트:** 2026-04-12
> **상태:** 기획 완료, 구현 대기
> **전제 환경:** Phase 5-0 로컬 Docker Compose ([03_local_docker_dev_environment.md](../5_0_infra_setting/03_local_docker_dev_environment.md))

---

## 1. Context — 왜 이 작업이 필요한가

Phase 4(딥 리포트 시스템)는 Python Chainlit UI로 동작 검증이 끝났다.
Phase 5-1은 Go API + Python Worker 백엔드를 로컬 Docker Compose에서 구현하는 단계이며,
**Phase 5-2**는 이 백엔드를 소비하는 **Next.js 프론트엔드**를 구현하는 단계다.

핵심 전환:

| 항목 | Phase 4 (현재) | Phase 5-2 (이번 단계) |
|------|---------------|---------------------|
| UI 프레임워크 | Python Chainlit | **Next.js 15 App Router (React 19, TypeScript)** |
| 인터뷰 플로우 | `cl.AskUserMessage` + `cl.AskActionMessage` | **4단계 React 폼 위자드** |
| 보고서 뷰어 | Chainlit 메시지 내 Markdown | **전용 뷰어 (사이드바 TOC + 마크다운 렌더러)** |
| 진행률 | 콘솔 print | **SSE 실시간 스트리밍 + 애니메이션 프로그레스 바** |
| 인증 | 없음 | **JWT + 카카오/네이버/Google 소셜 로그인** |
| 결제 | 없음 | **Toss Payments JS SDK 위젯** |
| 스타일링 | Chainlit 기본 테마 | **Tailwind CSS v4 + shadcn/ui, 모바일 퍼스트 (375px~)** |

> **중요:** Phase 4의 인터뷰 흐름(`codes/report/interview.py`)을 React 폼 위자드로 직접 전환한다.
> 프론트엔드는 단계별로 폼을 보여주고, 마지막에 한 번에 `POST /api/v1/reports` 페이로드를 보낸다.

### 본 단계에서 다루지 않는 것

- GCP 배포 (Phase 5-3에서 GKE + Cloud CDN으로 배포)
- Android/iOS 앱 (Phase 6 이후)
- 다크 모드 (Phase 5-3 이후 선택적 추가)
- 국제화(i18n) — MVP는 한국어 전용

---

## 2. 사용자 결정 사항 (2026-04-12 확정)

| 항목 | 결정 | 배경 |
|------|------|------|
| **소스코드 위치** | `/home/gon/ws/rag/codes/realtor-ai-frontend/` | rag 트리 안, 백엔드(`codes/realtor-ai-backend/`)와 동일 패턴 |
| **문서 범위** | 전체 7개 상세 작성 | 백엔드 문서(5-1)와 동일 수준 |
| **SSE 인증** | 쿼리 파라미터 토큰 (`?token=xxx`) | `EventSource` API는 커스텀 헤더 미지원. 구현 단순, 백엔드에 쿼리 파라미터 검증 추가 |
| **컴포넌트 라이브러리** | shadcn/ui + Radix UI | 코드 소유, 한국 소셜 로그인 브랜드 가이드라인 맞춤 가능 |
| **상태 관리** | TanStack Query (서버) + Zustand (클라이언트) | 인터뷰 위자드 다단계 상태는 Zustand, API 캐시는 TanStack Query |
| **폰트** | Pretendard Variable | Noto Sans KR 대비 가변 폰트 단일 파일, UI 한국어 간격 최적화 |

---

## 3. 기술 스택 요약

| 카테고리 | 선택 | 비고 |
|---------|------|------|
| 프레임워크 | Next.js 15 (App Router) | React 19, Turbopack dev |
| 언어 | TypeScript 5.x | strict mode |
| 스타일링 | Tailwind CSS v4 | 모바일 퍼스트 (375px~) |
| UI 프리미티브 | shadcn/ui + @radix-ui | 접근성 내장 |
| 서버 상태 | @tanstack/react-query v5 | 캐싱, 리패칭, 뮤테이션 |
| 클라이언트 상태 | Zustand | 인터뷰 위자드 상태 |
| 폼 핸들링 | react-hook-form v7 + zod | 타입 안전 검증 |
| 마크다운 | react-markdown + remark-gfm + rehype-raw | 보고서 뷰어 |
| 애니메이션 | Framer Motion | 스텝 전환, 프로그레스 |
| 아이콘 | lucide-react | 트리 셰이킹 |
| 토스트 | sonner | 경량, React 19 호환 |
| 결제 | @tosspayments/tosspayments-sdk | 공식 JS SDK |
| 테스트 | vitest + @testing-library/react + Playwright | 단위 + E2E |

> 상세 선택 근거는 [01_tech_stack_and_project_structure.md](01_tech_stack_and_project_structure.md) 참조.

---

## 4. 페이지 구조

```
/                          # 랜딩 페이지 (SSG)
/pricing                   # 요금제 (SSG)
/login                     # 소셜 로그인 + 이메일/비밀번호
/auth/callback             # OAuth 콜백 핸들러
/dashboard                 # 보고서 목록 + 이용 현황 (CSR, 인증 필요)
/reports/new               # 인터뷰 4단계 위자드 (CSR, 인증 필요)
/reports/[id]              # 보고서 뷰어 + SSE 진행률 (CSR, 인증 필요)
/settings                  # 프로필, 결제, 계정 관리 (CSR, 인증 필요)
```

| 페이지 | 렌더링 | 인증 | 핵심 기능 |
|--------|--------|------|----------|
| `/` | SSG | 불필요 | Hero, 가치 제안, 이용 방법, 가격 프리뷰 |
| `/pricing` | SSG | 불필요 | 요금제 카드 (무료/단건/패키지) |
| `/login` | CSR | 불필요 | 카카오/네이버/Google + 이메일 로그인 |
| `/auth/callback` | CSR | 불필요 | OAuth 토큰 추출, 세션 저장 → /dashboard 리다이렉트 |
| `/dashboard` | CSR | **필요** | 보고서 목록 (커서 페이지네이션), 크레딧 잔액, 사용량 |
| `/reports/new` | CSR | **필요** | 주소 입력→후보 선택→목적 선택→확인→보고서 생성 |
| `/reports/[id]` | CSR | **필요** | 진행 중: SSE 프로그레스. 완료: 마크다운 뷰어 + TOC |
| `/settings` | CSR | **필요** | 프로필, 결제 내역, 크레딧 충전, PIPA |

---

## 5. Sprint 로드맵

```
Sprint 0 (1일): 프로젝트 스캐폴드
  ├─ create-next-app + 의존성 설치
  ├─ Tailwind/ESLint/Vitest 설정
  ├─ Docker Compose frontend 연동 (FRONTEND_SRC_PATH)
  └─ 검증: http://localhost:3000 접속 + 핫 리로드 동작

Sprint 1 (5일): 인증 UI
  ├─ /login: 카카오/네이버/Google 소셜 로그인 + 이메일/비밀번호
  ├─ /auth/callback: OAuth 토큰 추출
  ├─ AuthProvider, useAuth 훅, middleware.ts 라우트 보호
  ├─ API 클라이언트 (토큰 주입, 401 자동 리프레시)
  └─ 검증: 소셜 로그인 → /dashboard 접근 가능

Sprint 2 (4일): 대시보드
  ├─ /dashboard: 보고서 목록 + 사용량 통계 + 크레딧 잔액
  ├─ 커서 기반 "더 보기" 페이지네이션
  ├─ 보고서 상태 뱃지 (대기중/생성중/완료/실패)
  └─ 검증: 보고서 목록 로드 + 삭제 동작

Sprint 3 (5-6일): 인터뷰 위자드
  ├─ /reports/new: 4단계 폼 위자드
  │   Step 1: 주소 텍스트 입력 + 디바운싱 자동완성
  │   Step 2: 카카오 지오코딩 후보 카드 선택
  │   Step 3: 분석 목적 선택 (6종 + 기타)
  │   Step 4: 요약 확인 + 보고서 생성 시작
  ├─ Zustand 인터뷰 스토어
  ├─ Framer Motion 스텝 전환 애니메이션
  └─ 검증: 전체 플로우 → POST /reports → /reports/[id]로 이동

Sprint 4 (5일): 보고서 뷰어 + SSE 진행률
  ├─ /reports/[id]: 진행 중 → SSE 프로그레스 바 (7단계)
  ├─ /reports/[id]: 완료 → 마크다운 뷰어 + 사이드바 TOC
  ├─ useEventSource 훅 (쿼리 파라미터 토큰 인증)
  ├─ react-markdown 커스텀 렌더러
  └─ 검증: SSE 진행률 실시간 표시 → 완료 시 뷰어 전환

Sprint 5 (3일): 랜딩 + 가격 페이지
  ├─ /: SSG 랜딩 (Hero, 가치 제안, CTA)
  ├─ /pricing: SSG 요금제
  ├─ SEO 메타태그, OG
  └─ 검증: Lighthouse 성능 90+, SEO 90+

Sprint 6 (5일): 설정 + 결제
  ├─ /settings: 프로필/이용내역/결제/계정 탭
  ├─ Toss Payments SDK 위젯 (prepare → confirm)
  ├─ PIPA: 데이터 내보내기, 계정 삭제/철회
  └─ 검증: Toss 테스트 모드 결제 → 크레딧 충전 확인

Sprint 7 (4일): 폴리시
  ├─ 전역 에러 핸들링 (에러 바운더리, 한국어 에러 메시지)
  ├─ 로딩 스켈레톤, 빈 상태 UI
  ├─ 모바일 최적화 (375px, 터치 타겟 44px+)
  ├─ 접근성 (ARIA, 키보드 내비게이션)
  ├─ Playwright E2E 전체 사용자 여정 테스트
  └─ 검증: E2E 100% 통과, Lighthouse 접근성 95+
```

**총 기간: 약 32-33일**

---

## 6. 백엔드 스프린트 의존 관계

```
Frontend Sprint          Backend Sprint Required
──────────────────────────────────────────────────
F-Sprint 0 (스캐폴드)    없음
F-Sprint 1 (인증 UI)     B-Sprint 1 (인증 시스템)
F-Sprint 2 (대시보드)    B-Sprint 2 (보고서 CRUD) + B-Sprint 3 (사용자/사용량)
F-Sprint 3 (인터뷰)     B-Sprint 2 (POST /reports) + B-Sprint 3 (POST /address/resolve)
F-Sprint 4 (보고서 뷰어) B-Sprint 2 (GET /reports/{id}, SSE)
F-Sprint 5 (랜딩/가격)   없음 (정적 페이지)
F-Sprint 6 (설정/결제)   B-Sprint 3 (사용자) + B-Sprint 4 (결제)
F-Sprint 7 (폴리시)     전체 백엔드 완료
```

**병렬 실행 가능:**
- F-Sprint 0은 즉시 시작 가능 (백엔드 무관)
- F-Sprint 5 (랜딩/가격)은 언제든 삽입 가능 (정적 페이지)
- 백엔드 대기 시 MSW(Mock Service Worker)로 API 모킹하여 프론트엔드 개발 진행 가능

---

## 7. Docker Compose 연동

### 7.1 frontend 서비스 (`codes/local-infra/docker-compose.yml` 라인 233-262)

```yaml
frontend:
  image: node:20-alpine
  container_name: realtor-frontend
  ports:
    - "${FRONTEND_PORT:-3000}:3000"
  working_dir: /app
  volumes:
    - ${FRONTEND_SRC_PATH:-./placeholder/frontend}:/app
    - npmcache:/root/.npm
  environment:
    NEXT_PUBLIC_API_URL: http://localhost:${GO_API_PORT:-8080}
    NEXT_PUBLIC_STORAGE_URL: http://localhost:${MINIO_API_PORT:-9000}
    NODE_ENV: development
  command: >
    sh -c '
      if [ -f package.json ]; then
        npm install && npm run dev
      else
        echo "=== Next.js 소스코드 미연결 ===" &&
        tail -f /dev/null
      fi
    '
  depends_on:
    go-api:
      condition: service_started
  networks:
    - realtor-net
```

### 7.2 .env 설정

```bash
# codes/local-infra/.env에 추가
FRONTEND_SRC_PATH=/home/gon/ws/rag/codes/realtor-ai-frontend
FRONTEND_PORT=3000
```

### 7.3 핫 리로드

Next.js 15 Turbopack은 파일 시스템 이벤트로 핫 리로드. Docker 볼륨 마운트에서 이벤트가 전파되지 않을 경우:

```yaml
environment:
  WATCHPACK_POLLING: "true"  # 폴링 모드 활성화
```

---

## 8. Phase 4 코드와의 연동 지점

| Phase 4 자산 | 위치 | 5-2에서의 사용 |
|-------------|------|-------------|
| 인터뷰 4단계 | [codes/report/interview.py:32](../../../../codes/report/interview.py#L32) | React 폼 위자드로 전환 (Step 1~4 로직 참조) |
| 목적 선택 enum | [codes/report/interview.py:169](../../../../codes/report/interview.py#L169) | `매매_실거주`, `매매_투자`, `매도`, `전세`, `경매`, `기타` |
| AddressCandidate | [codes/api/models/address.py](../../../../codes/api/models/address.py) | TypeScript 타입 미러링 |
| UserContext | [codes/report/state.py](../../../../codes/report/state.py) | `purpose`, `custom_notes` → POST /reports 페이로드 |
| 진행률 스텝 매핑 | [codes/realtor-ai-worker/progress.py](../../../../codes/realtor-ai-worker/progress.py) (예정) | SSE 이벤트의 7단계: 주소 정규화(10%)→데이터 수집(30%)→차트(45%)→세금(50%)→보고서(75%)→요약(90%)→완료(100%) |
| 보고서 섹션 | 7개 타입 | `location`, `price`, `legal`, `investment`, `sunview`, `risk`, `future` |

---

## 9. 하위 문서 가이드

| 문서 | 내용 |
|------|------|
| [01_tech_stack_and_project_structure.md](01_tech_stack_and_project_structure.md) | 라이브러리 선택 근거, 디렉토리 구조, 디자인 토큰, API 클라이언트 |
| [02_sprint0_scaffold.md](02_sprint0_scaffold.md) | Sprint 0: 프로젝트 초기화, Docker 연동, 기본 설정 |
| [03_sprint1_auth_ui.md](03_sprint1_auth_ui.md) | Sprint 1: 인증 UI, OAuth 플로우, 토큰 관리 |
| [04_sprint2_3_dashboard_interview.md](04_sprint2_3_dashboard_interview.md) | Sprint 2-3: 대시보드 + 4단계 인터뷰 위자드 |
| [05_sprint4_report_viewer.md](05_sprint4_report_viewer.md) | Sprint 4: 보고서 뷰어, SSE 진행률, 마크다운 렌더러 |
| [06_sprint5_6_7_landing_settings_polish.md](06_sprint5_6_7_landing_settings_polish.md) | Sprint 5-7: 랜딩/가격/설정/결제/폴리시 |

---

## 10. 검증 (전체 5-2 종료 조건)

본 단계 전체가 종료되는 시점은 다음 시나리오가 로컬 Docker Compose에서 100% 통과할 때다:

1. **소셜 로그인**: 카카오 OAuth로 가입 → JWT 발급 → `/dashboard` 접근
2. **대시보드**: 보고서 목록 로드, 빈 상태 → "새 보고서 생성" CTA 표시
3. **인터뷰 위자드**: 주소 입력("마포래미안푸르지오") → 후보 선택 → 목적 선택 → 확인 → `POST /reports` → `/reports/[id]`
4. **SSE 진행률**: `/reports/[id]`에서 7단계 진행률 실시간 표시 (10%→30%→45%→50%→75%→90%→100%)
5. **보고서 뷰어**: 완료된 보고서의 모든 섹션 + 차트 이미지가 마크다운 뷰어에 렌더링
6. **결제**: Toss 테스트 모드 결제 → 크레딧 충전 → 추가 보고서 생성 가능
7. **PIPA**: `/settings`에서 데이터 내보내기 → JSON 다운로드. 계정 삭제 요청 → 이후 로그인 불가
8. **모바일**: 375px 뷰포트에서 전체 플로우 사용 가능
9. **에러 복구**: API 서버 다운 시 사용자 친화적 에러 메시지 표시
10. **성능**: Lighthouse Performance 90+, Accessibility 95+, SEO 90+
