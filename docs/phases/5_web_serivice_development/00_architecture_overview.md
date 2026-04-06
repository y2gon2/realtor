# Phase 5: 프로덕션 웹 서비스 배포 — 아키텍처 설계서

> **최종 업데이트:** 2026-04-06  
> **상태:** 설계 완료, 구현 대기

---

## 1. Context

Phase 4 딥 리포트 시스템이 로컬 프로토타입(Python + Chainlit + Docker Compose)으로 동작 검증 완료.
이를 GCP 기반 프로덕션 웹 서비스로 전환하기 위한 전체 아키텍처 설계.

**핵심 전환:**

| 항목 | 현재 (Phase 4) | 목표 (Phase 5) |
|------|----------------|----------------|
| 백엔드 | Python (Chainlit) | Go API + Python ML Worker |
| 프론트엔드 | Chainlit 웹 UI | Next.js (React/TypeScript) |
| 인프라 | 로컬 Docker Compose | GCP GKE Autopilot |
| DB | 없음 (파일 기반) | PostgreSQL + PostGIS + Redis |
| 인증 | 없음 | JWT + 소셜 로그인 (카카오/네이버/Google) |
| 결제 | 없음 | Toss Payments (카드/네이버페이/카카오페이) |

**서비스 조건:**
- 서비스 지역: 대한민국 한정 (1년 내 해외 확장 없음)
- 1차: 백엔드 + 웹 프론트엔드
- 2차: Android 앱 (1-2개월 후)
- 3차: iOS 앱 (2-3개월 후)

---

## 2. 클라우드 제공자: GCP Seoul (asia-northeast3)

### 선정 근거

| 기준 | GCP Seoul | NCP (네이버 클라우드) | 판정 |
|------|-----------|----------------------|------|
| 매니지드 서비스 성숙도 | GKE Autopilot, Cloud SQL, Memorystore | NKS, Cloud DB — 자동화 미흡 | **GCP** |
| Terraform/IaC | 퍼스트클래스 프로바이더, 풍부한 문서 | 프로바이더 존재, 커버리지 부족 | **GCP** |
| 개발자 생태계 | Go/Python 공식 SDK, 글로벌 커뮤니티 | 한국어 문서 위주, 소규모 커뮤니티 | **GCP** |
| GPU 지원 | T4/L4 Autopilot 자동 프로비저닝 | GPU 서버 수동 구성 | **GCP** |
| 한국 API 레이턴시 | 서울 리전: ~5ms | 국내 DC: ~3ms | NCP (무의미) |
| 컴플라이언스 | CSAP 인증, PIPA 충족 | 국내 클라우드, 규제 위상 우세 | 동등 |
| MVP 비용 | ~$430/월 (인프라) | ~$365-438/월 | 동등 |

**결론:** 매니지드 서비스 완성도, GKE Autopilot 운영 효율, Terraform 생태계가 결정적.
한국 API 레이턴시 차이(2-3ms)는 보고서 생성 대비 무의미.
NCP는 정부 조달/공공기관 프로젝트가 아닌 한 불필요.

---

## 3. 인프라 아키텍처

```
Internet
    │
    ▼
Global External Application Load Balancer (HTTPS, Google-managed SSL)
    │
    ├──► Cloud CDN ──► Cloud Storage (프론트엔드 정적 자산)
    │
    └──► GKE Autopilot Cluster (asia-northeast3)
          │
          ├── go-api (Deployment, 2-10 replicas, HPA)
          │     Go API 서버: 인증, 결제, 보고서 CRUD, SSE 진행률
          │
          ├── python-worker (Deployment, 1-8 replicas, HPA by queue depth)
          │     보고서 생성 워커: Redis Stream 소비
          │     → 기존 ReportOrchestrator 파이프라인 실행
          │
          ├── qdrant (StatefulSet, 1 replica → 3 HA)
          │     벡터 DB: ~100K 벡터, 20Gi SSD PVC
          │
          └── embedding-server (Deployment, 1 replica, GPU: T4)
                BGE-M3 임베딩 서비스 (FastAPI + gRPC)
    │
    ├──► Cloud SQL (PostgreSQL 15 + PostGIS)
    │       MVP: db-custom-2-7680, 단일 존
    │       성장: db-custom-4-16384, 리전 HA
    │       Private IP only, 자동 백업 7일
    │
    ├──► Memorystore (Redis 7.0)
    │       MVP: 1GB Basic → 성장: 5GB Standard HA
    │       용도: API 캐시, 세션, 잡 큐, Rate Limit
    │
    └──► Cloud Storage
            reports-pdf, chart-images 버킷
            Signed URL (4시간 만료) PDF 다운로드
```

### 컴퓨트 선택: GKE Autopilot (Cloud Run 대비)

- SSE/WebSocket 영구 연결 필요 (진행률 스트리밍)
- Qdrant StatefulSet + GPU 노드풀 → Cloud Run 불가
- Python Worker의 Redis Stream 소비 패턴 → Cloud Run 부적합
- Autopilot: 노드 관리 없이 Pod 단위 과금 → 운영 부담 최소화

### 데이터베이스 스키마 (핵심)

```sql
users (id, email, name, auth_provider, provider_id, tier, created_at)

reports (id, user_id FK, address_input, normalized_address JSONB,
         purpose, status ENUM, pdf_url, generation_time_ms, created_at)

report_sections (id, report_id FK, section_type ENUM, content TEXT,
                 generation_time_ms)

payments (id, user_id FK, pg_provider, pg_transaction_id,
          amount, status, product_type, created_at)

api_cache (cache_key, response JSONB, expires_at,
           geom GEOMETRY(Point, 4326))  -- PostGIS 공간 쿼리
```

---

## 4. 백엔드 아키텍처 (Go)

### 4.1 모듈러 모놀리스 구조

MVP에서 마이크로서비스는 과도한 복잡성. 단일 Go 바이너리, 내부 패키지 경계:

```
go-api/
├── cmd/server/main.go
├── internal/
│   ├── auth/           # JWT + OAuth2 (카카오/네이버/Google 동등 지원)
│   ├── user/           # 사용자 CRUD, 프로필, PIPA 데이터 관리
│   ├── payment/        # Toss Payments 통합 (카드/네이버페이/카카오페이)
│   ├── report/
│   │   ├── handler.go  # HTTP 핸들러
│   │   ├── service.go  # 비즈니스 로직 (잡 큐 발행)
│   │   └── models.go   # 도메인 모델
│   ├── api/            # 한국 공공 API 클라이언트 (Go 재구현)
│   │   ├── client.go   # 베이스 클라이언트 (retry, rate-limit, cache)
│   │   └── kakao.go    # 주소 정규화 (인터뷰 Step 1 즉시 응답용)
│   ├── cache/          # Redis 추상화
│   ├── middleware/      # 인증, Rate Limit, CORS, 로깅
│   └── sse/            # 보고서 진행률 SSE 스트리밍
├── migrations/          # golang-migrate SQL
├── pkg/proto/           # gRPC protobuf (RAG 쿼리용)
└── Dockerfile
```

**라이브러리:** `chi` (라우터), `sqlc` (타입-세이프 SQL), `golang-migrate` (마이그레이션)

### 4.2 API 엔드포인트

```
# 인증 (카카오/네이버/Google 동등 지원)
POST   /api/v1/auth/signup
POST   /api/v1/auth/login
POST   /api/v1/auth/oauth/{kakao|naver|google}
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

# 보고서
POST   /api/v1/reports                  # 생성 (잡 큐 발행)
GET    /api/v1/reports                  # 목록 (페이징)
GET    /api/v1/reports/{id}             # 상세
GET    /api/v1/reports/{id}/pdf         # PDF 다운로드 (Signed URL)
GET    /api/v1/reports/{id}/progress    # SSE 진행률 스트림

# 주소
POST   /api/v1/address/resolve          # 주소 정규화 (카카오 지오코딩)

# 결제 (Toss Payments — 카드/네이버페이/카카오페이 통합)
POST   /api/v1/payments/prepare         # 결제 세션 생성
POST   /api/v1/payments/confirm         # 결제 승인 확인
GET    /api/v1/payments/history         # 결제 내역

# 사용자
GET    /api/v1/user/profile
PUT    /api/v1/user/profile
GET    /api/v1/user/usage               # 이용 현황, 잔여 크레딧
DELETE /api/v1/user/account             # 회원 탈퇴 (PIPA)
GET    /api/v1/user/data-export         # 개인정보 다운로드 (PIPA)
```

### 4.3 인증: JWT + 소셜 로그인

- **JWT:** Access Token (15분) + Refresh Token (7일, Redis 저장)
- **소셜 로그인 (3사 동등 지원):**
  - **카카오** OAuth2 — 한국 최대 메신저 기반, 필수
  - **네이버** OAuth2 — 한국 최대 포털, 필수
  - **Google** OAuth2 — 글로벌 사용자, 동등 지원
  - 모두 Authorization Code Flow
- **비밀번호 인증:** bcrypt, 이메일/비밀번호 선호 사용자용 선택 옵션

### 4.4 결제: Toss Payments (카드 + 네이버페이 + 카카오페이)

#### PG 선정: Toss Payments

| 기준 | Toss Payments | PortOne + PG | 자체 직접 통합 |
|------|--------------|-------------|--------------|
| 네이버페이 | 네이티브 지원 | PG 경유 지원 | 별도 API 필요 |
| 카카오페이 | 네이티브 지원 | PG 경유 지원 | 별도 API 필요 |
| 신용카드 | 직접 처리 | PG 경유 | 별도 PG 필요 |
| 계약 수 | **1건** | 2건 (PortOne + PG) | **3건** (카카오+네이버+PG) |
| 통합 대시보드 | 통합 | PortOne 통합 | 3개 분리 |
| 개발 난이도 | **낮음** (1 API) | 낮음 (1 API) | 높음 (3 API) |
| PG 교체 유연성 | 낮음 | **높음** | 해당 없음 |
| 수수료 | 2.5-3.5% (카드) | PG 수수료 동일 | 2.0-3.5% |

**선정:** Toss Payments 직접 통합 — 1건 계약으로 카드/네이버페이/카카오페이/토스페이 모두 처리.
향후 PG 교체 필요시 결제 추상화 레이어 또는 PortOne 전환으로 대응.

> **참고:** 연 매출 3억 이하 소기업은 카드 수수료 0.4% 적용 (2025 규정)

#### 결제 플로우

```
1. 프론트엔드 → POST /api/v1/payments/prepare (상품 정보)
2. Go 백엔드 → Toss Payments API 세션 생성 → paymentKey 반환
3. 프론트엔드 → Toss 결제 위젯 렌더링 (JS SDK)
   → 사용자가 카드/네이버페이/카카오페이 중 선택
4. 결제 완료 → Toss 성공 URL 리다이렉트
5. 프론트엔드 → POST /api/v1/payments/confirm
6. Go 백엔드 → Toss 서버 간 승인 확인 → 크레딧 충전, DB 기록
```

**PCI DSS 범위:** SAQ-A — Toss 호스팅 위젯 사용으로 카드 데이터 서버 미경유

### 4.5 보고서 비동기 처리: Redis Streams

```
[Go API]                              [Python Worker]
   │                                       │
   ├─ POST /reports ─────────────────┐     │
   │  → 크레딧 확인                    │     │
   │  → reports INSERT (PENDING)     │     │
   │  → Redis Stream XADD ──────────┼────►│ XREADGROUP 소비
   │  → 202 Accepted                 │     │
   │                                 │     ├─ ReportOrchestrator.generate()
   │  GET /reports/{id}/progress     │     │   (주소정규화→API수집→차트→룰엔진→LLM)
   │  ← SSE ◄────────────────────────┼─────┤ Redis PUBLISH progress
   │                                 │     │
   │                                 │     ├─ PDF → Cloud Storage
   │                                 │     └─ reports UPDATE (COMPLETED)
```

### 4.6 Go ↔ Python 역할 분리

| 컴포넌트 | 언어 | 사유 |
|----------|------|------|
| API 서버, 인증, 결제, 사용자 관리 | **Go** | 동시성, 메모리 효율, 정적 타입 |
| 주소 정규화 (카카오 지오코딩) | **Go** (간단 버전) | 인터뷰 Step 1 즉시 응답 |
| 보고서 생성 파이프라인 전체 | **Python** (기존 코드) | 검증 완료, asyncio, Anthropic SDK |
| RAG 검색 | **Python** (기존) | 임베딩 모델 + Qdrant 연동 |
| 룰 엔진 (세금/대출) | **Python** (기존) | 초기 유지, 성능 필요시 Go 포팅 |
| 차트 생성 | **Python** (matplotlib) | 서버사이드 렌더링 |

---

## 5. 프론트엔드 아키텍처 (Next.js + TypeScript)

### 5.1 프레임워크: Next.js App Router

- **SSG:** 랜딩, 가격, 블로그 → SEO + 빠른 로딩
- **CSR:** 대시보드, 보고서 뷰어 → 인증 필요, SEO 불필요
- **Tailwind CSS** 모바일 퍼스트 반응형 (375px~)

### 5.2 페이지 구조

```
/                          # 랜딩 페이지 (SSG)
/pricing                   # 요금제 (SSG)
/login                     # 소셜 로그인 (카카오/네이버/Google)
/dashboard                 # 보고서 목록, 이용 현황 (CSR)
/reports/new               # 인터뷰 플로우 4단계 (CSR)
/reports/[id]              # 보고서 뷰어 + 진행률 (CSR)
/reports/[id]/pdf          # PDF 미리보기/다운로드
/settings                  # 프로필, 결제 수단 (CSR)
```

### 5.3 진행률 SSE 스트리밍

```typescript
const evtSource = new EventSource(`/api/v1/reports/${reportId}/progress`);
evtSource.onmessage = (event) => {
  const { step, detail, progress } = JSON.parse(event.data);
  // step: "데이터 수집", detail: "실거래가 API 조회 중...", progress: 35
};
```

진행 단계 (orchestrator.py on_progress 매핑):
1. 주소 정규화 (10%) → 2. 데이터 수집 (30%) → 3. 차트 생성 (45%)
4. 세금/대출 계산 (50%) → 5. 보고서 생성 (75%) → 6. 요약 (90%) → 7. 완료 (100%)

### 5.4 배포

- Cloud Storage (정적 자산) + Cloud Run (SSR)
- Cloud CDN → 정적 자산 앞단
- 차트 이미지: 2x DPI 렌더링, `max-width: 100%` 반응형

---

## 6. 시스템 처리 용량 분석

### 6.1 Go API 서버 처리량

Go `net/http`는 goroutine 기반 동시성 → 단일 인스턴스에서 높은 RPS 처리 가능.

**요청당 레이턴시 분석:**

| 컴포넌트 | 레이턴시 | 비고 |
|----------|---------|------|
| JWT 검증 (HS256) | ~2-5 us | 인메모리, CPU |
| Redis 캐시 읽기 | ~0.2-0.5 ms | 로컬 네트워크 |
| PostgreSQL CRUD | ~1-5 ms | 커넥션 풀, 인덱스 |
| JSON 직렬화 | ~10-50 us | 페이로드 크기 의존 |
| **요청당 총합** | **~2-6 ms** | P50 추정 |

**단일 인스턴스(4 vCPU) RPS:**

| 시나리오 | RPS (지속) |
|----------|-----------|
| 캐시 히트 (Redis only) | 15,000-25,000 |
| 혼합 CRUD (70% R / 30% W) | 5,000-10,000 |
| 쓰기 집중 (DB 트랜잭션) | 3,000-6,000 |

### 6.2 DAU별 처리량 분석

**산정 기준:**
- 동시접속 비율: DAU의 5-10% (비소셜 앱 산업 평균)
- 세션당 API 호출: 20-50건
- 피크/평균 비율: 3-5x (한국 저녁 시간대 20-22시)

| DAU | 피크 동시접속 | 피크 RPS | SSE 연결 | 보고서/일 | Go Pod 수 | Pod 사양 |
|-----|-------------|---------|---------|----------|----------|---------|
| 500 | 25-50 | 5-15 | 5-15 | 150-300 | **1+1 (HA)** | 250m, 512Mi |
| 1,000 | 50-100 | 15-40 | 10-30 | 300-600 | **1+1 (HA)** | 500m, 512Mi |
| 5,000 | 250-500 | 80-200 | 50-150 | 1,500-3,000 | **2 (min2/max4)** | 1 vCPU, 1Gi |
| 10,000 | 500-1,000 | 200-500 | 100-300 | 3,000-6,000 | **2-3 (min2/max6)** | 2 vCPU, 2Gi |

**결론: Go 모놀리스는 10,000 DAU까지 2-3 Pod으로 충분히 수용 가능.**
단일 Pod(2 vCPU)이 5,000+ RPS 처리 가능 → 10,000 DAU 피크 200-500 RPS 대비 10-25x 여유.

### 6.3 SSE 동시 연결 용량

- goroutine당 메모리: ~20-50 KB (idle 상태)
- 1,000 연결: ~20-50 MB → 무시 가능
- 10,000 연결: ~200-500 MB → 1-2 GB Pod에서 여유
- 50,000 연결: ~1-2.5 GB → 전용 메모리 필요

**10,000 DAU 기준 동시 SSE ~300개 → 완전히 여유.**

### 6.4 Python Worker 처리량

Claude API 사용 시 보고서당 소요 시간: **~15-30초** (병렬 LLM 호출)

| 보고서/일 | 피크 시간당 | 필요 워커 | Pod 사양 | 비고 |
|----------|-----------|---------|---------|------|
| 300 | ~50/hr | **1-2** | 500m, 1Gi | 1 Pod, 2 async 워커 |
| 800 | ~130/hr | **2-3** | 500m, 1Gi | 1-2 Pod |
| 3,000 | ~500/hr | **5-8** | 1 vCPU, 2Gi | Claude Tier 3+ 필요 |
| 8,000 | ~1,300/hr | **12-15** | 1 vCPU, 2Gi | Claude Tier 4 필요 |

### 6.5 병목 분석 (시스템 전체)

```
병목 순서 (가장 먼저 → 가장 나중에 발생):

1위. Claude API Rate Limit / 비용  ← 핵심 병목
     Tier 1: 50 RPM → MVP에서도 피크 시 부족
     Tier 2: 1,000 RPM → 800 보고서/일까지
     Tier 3-4: 4,000 RPM → 8,000 보고서/일 대응

2위. Python Worker 수  ← 수평 확장으로 해소

3위. PostgreSQL  ← 5,000 DAU 이후 PgBouncer + Read Replica

4위. Redis  ← 100K+ ops/sec, 병목 가능성 매우 낮음

5위. Go API  ← 10x+ 여유, 사실상 병목 불가
```

**결론: 성장 단계 3 (10,000 DAU, 8,000 보고서/일)까지 Go 모놀리스 + Python Worker 수평 확장으로 충분히 수용 가능. 실제 병목은 Claude API Rate Limit이며, Tier 업그레이드로 해소.**

---

## 7. LLM 비용 상세 분석

### 7.1 보고서당 토큰 사용량 (실측 기반)

기존 코드 `codes/report/prompts/` 프롬프트 파일 및 `test_v1/` 테스트 출력 기반 측정.
한국어 토큰화 비율: ~1.7 토큰/글자.

| 섹션 | 시스템 프롬프트 | 데이터 컨텍스트 | 출력 | 입력 소계 | 출력 소계 |
|------|--------------|--------------|------|----------|----------|
| 가격/시세 분석 | ~600 tok | ~8,000 tok | ~4,750 tok | 8,600 | 4,750 |
| 입지 분석 | ~550 tok | ~5,500 tok | ~4,130 tok | 6,050 | 4,130 |
| 법률/규제 분석 | ~650 tok | ~4,500 tok | ~5,610 tok | 5,150 | 5,610 |
| 투자 수익률 | ~500 tok | ~5,500 tok | ~5,780 tok | 6,000 | 5,780 |
| 요약 결론 | ~680 tok | ~3,620 tok | ~1,100 tok | 4,300 | 1,100 |
| **합계** | **~2,980** | **~27,120** | **~21,370** | **~30,100** | **~21,370** |

**보고서당 총 토큰: ~51,500 (입력 30,100 + 출력 21,370)**

### 7.2 보고서당 비용 (모델별)

| 전략 | 입력 비용 | 출력 비용 | **보고서당** |
|------|---------|---------|------------|
| 전체 Sonnet 4.6 ($3/$15 MTok) | $0.090 | $0.321 | **$0.411** |
| 전체 Haiku 4.5 ($1/$5 MTok) | $0.030 | $0.107 | **$0.137** |
| **혼합** (Haiku: 입지/법률, Sonnet: 가격/투자/요약) | $0.054 | $0.185 | **$0.239** |

> **비용 구조 특징:** 출력 토큰이 전체 비용의 **78%** 차지 (Sonnet 출력 $15/MTok vs 입력 $3/MTok)

### 7.3 월간 비용 (규모별)

| 규모 | 보고서/일 | 전체 Sonnet | **혼합 전략** | 전체 Haiku |
|------|----------|------------|-------------|-----------|
| MVP | 300 | $3,699/월 | **$2,151/월** | $1,233/월 |
| 성장 1 | 800 | $9,864/월 | **$5,736/월** | $3,288/월 |
| 성장 2 | 3,000 | $36,990/월 | **$21,510/월** | $12,330/월 |
| 성장 3 | 8,000 | $98,640/월 | **$57,360/월** | $32,880/월 |

### 7.4 프롬프트 캐싱 효과

시스템 프롬프트(~2,980 토큰)만 캐싱 가능 → 전체 입력의 ~10%.
출력 토큰(비용의 78%)은 캐싱 불가.

| 항목 | 값 |
|------|-----|
| 캐싱 가능 토큰 비율 | ~10% (입력 중) |
| 캐시 히트 시 입력 비용 절감 | ~9% |
| **전체 비용 절감** | **~2-3%** |

**프롬프트 캐싱은 보조적 효과. 핵심 최적화는 모델 계층화와 출력 토큰 절감.**

### 7.5 비용 최적화 전략 (영향도 순)

| 순위 | 전략 | 절감 효과 | 적용 난이도 |
|------|------|---------|-----------|
| 1 | **모델 계층화** (Haiku: 입지/법률, Sonnet: 가격/투자/요약) | ~42% | 낮음 (기존 llm_client 지원) |
| 2 | **출력 토큰 제한** (포맷 지시: "정확히 4개 핵심 포인트, 항목당 50단어") | ~23% | 낮음 (프롬프트 수정) |
| 3 | **Batch API** (비실시간 인기 단지 사전 생성) | ~50% (해당분) | 중간 |
| 4 | **보고서 캐싱** (동일 단지+목적 24시간 재활용) | ~15-30% | 낮음 |
| 5 | **Haiku 전체 + Sonnet 리뷰** (Haiku로 전체 생성 → Sonnet 1회 검수) | ~55% | 중간 |

**권장 초기 전략: 혼합 모델 ($0.239/보고서) → MVP $2,151/월**
기존 `APILLMClient.generate()` (codes/generation/llm_client.py)가 per-call 모델 오버라이드 지원 → 코드 변경 최소.

---

## 8. 종합 비용 분석

### 8.1 MVP 월간 비용 (100-500 DAU, ~300 보고서/일)

| 항목 | 구성 | 월 비용 (USD) |
|------|------|---------------|
| GKE Autopilot (Go API) | 2 Pod × 250m CPU, 512Mi | ~$36 |
| GKE Autopilot (Python Worker) | 1 Pod × 500m CPU, 1Gi | ~$40 |
| GKE Autopilot (Qdrant) | 1 Pod × 1 vCPU, 2Gi, 20Gi PVC | ~$55 |
| GKE Autopilot (Embedding, T4 GPU) | 1 Pod × 12hr/일 | ~$110 |
| Cloud SQL | db-custom-2-7680, 20GB SSD, 단일 존 | ~$95 |
| Memorystore Redis | 1GB Basic | ~$50 |
| Cloud Storage | 50GB + 이그레스 | ~$5 |
| Load Balancer + CDN | 1 포워딩 룰 + 경량 트래픽 | ~$35 |
| 기타 (Monitoring, Secret Manager, DNS) | | ~$15 |
| **인프라 소계** | | **~$441/월** |
| **Anthropic API (혼합 전략)** | 300 보고서/일 × $0.239 | **~$2,151/월** |
| 한국 공공 API | data.go.kr, Kakao, KOSIS 등 | $0 |
| **총 합계** | | **~$2,592/월 (~₩3.6M)** |

### 8.2 성장 단계별 비용

| 단계 | DAU | 보고서/일 | 인프라 | LLM (혼합) | **합계** |
|------|-----|----------|--------|-----------|---------|
| MVP | 500 | 300 | $441 | $2,151 | **$2,592** |
| 성장 1 | 1,000 | 800 | $600 | $5,736 | **$6,336** |
| 성장 2 | 5,000 | 3,000 | $1,100 | $21,510 | **$22,610** |
| 성장 3 | 10,000 | 8,000 | $2,200 | $57,360 | **$59,560** |

> 인프라는 부선형(sub-linear) 증가, LLM은 선형 증가 → LLM 비용이 총비용의 80-95%.
> 비용 최적화의 핵심은 LLM 최적화 (모델 계층화, 출력 제한, 캐싱).

### 8.3 수익 모델 역산

| 티어 | 가격/월 | 보고서/월 | 보고서당 원가 | 마진 |
|------|---------|----------|-------------|------|
| 무료 | ₩0 | 2회 | ~₩340 (~$0.239) | - |
| 베이직 | ₩9,900 | 10회 | ~₩340 | ~66% |
| 프로 | ₩29,900 | 무제한(30) | ~₩340 | ~66%+ |
| 단건 | ₩1,900/건 | 1회 | ~₩340 | ~82% |

---

## 9. 보안 아키텍처

### 9.1 API 보안

- **Rate Limiting:** 인증 60 req/min (일반), 5 req/min (보고서 생성)
- **입력 검증:** Go `validator`, 주소 새니타이징
- **CORS:** `https://app.{domain}` + localhost (개발)
- **Cloud Armor:** WAF (SQL Injection, XSS), DDoS 방어

### 9.2 데이터 암호화

- **전송:** TLS 1.3 (LB 종단), GKE 내부 mTLS (프로덕션)
- **저장:** Cloud SQL/Storage/PVC 기본 암호화
- **앱 레벨:** 민감 정보 (전화번호, 실명) → AES-256 + KMS

### 9.3 개인정보보호법 (PIPA) 준수

| 요건 | 대응 |
|------|------|
| 데이터 거주 | GCP 서울 리전 한정 |
| 개인정보처리방침 | 회원가입 시 명시적 동의 |
| 최소 수집 | 이메일, 이름만, 불필요 정보 미수집 |
| 열람/삭제권 | `/user/data-export`, `/user/account` DELETE |
| 침해 통보 | 72시간 내 통보, 접근 로그 모니터링 |
| DPA | GCP PIPA 호환 DPA 체결 |

### 9.4 결제 보안

- Toss Payments 호스팅 위젯 → PCI SAQ-A (카드 데이터 서버 미경유)
- 카드번호/CVV 절대 미저장
- Webhook HMAC-SHA256 서명 검증

### 9.5 시크릿 관리: Google Secret Manager

모든 API 키, DB URL, JWT Secret → Secret Manager 저장.
GKE Workload Identity → 키 파일 없이 접근. 분기 1회 로테이션.

---

## 10. DevOps & CI/CD

### 10.1 CI/CD (GitHub Actions)

```
PR:
  ├── Go: golangci-lint → go test → go build
  ├── Python: ruff → pytest → docker build
  ├── Frontend: eslint → vitest → next build
  └── Security: trivy, gitleaks

main 머지:
  ├── 이미지 빌드 → Artifact Registry
  ├── staging 배포 → 스모크 테스트
  └── 수동 승인 → production 배포
```

### 10.2 환경

| 환경 | 인프라 | 용도 |
|------|--------|------|
| Local | Docker Compose | 개발 |
| Staging | GKE (staging NS) | 사전 검증 |
| Production | GKE (production NS) | 라이브 |

### 10.3 모니터링 & 알림

- **메트릭:** GMP (Prometheus) — 보고서 레이턴시, API 성공률, LLM 토큰, 큐 깊이
- **로깅:** Cloud Logging (Go `slog`, Python `structlog`)
- **트레이싱:** Cloud Trace (OpenTelemetry)
- **알림:** P0 (에러 5%+, 실패 10%+), P1 (p95 > 2s), P2 (디스크 80%+)

### 10.4 IaC (Terraform)

```
terraform/
├── environments/{staging,production}/main.tf
├── modules/{gke,cloudsql,memorystore,storage,networking,iam,loadbalancer}/
└── backend.tf  # GCS 원격 상태
```

---

## 11. 개발 타임라인

### Phase 0: 인프라 (1-2주차)

- [ ] GCP 프로젝트 + Terraform (VPC, GKE, Cloud SQL, Memorystore, Storage)
- [ ] CI/CD 파이프라인 (GitHub Actions)
- [ ] 컨테이너 이미지 스켈레톤
- [ ] DB 마이그레이션 프레임워크
- [ ] 도메인 + SSL 설정

### Phase 1-A: 백엔드 코어 (3-4주차)

- [ ] Go 프로젝트 구조 (`chi`, `sqlc`, 미들웨어)
- [ ] DB 스키마 + 마이그레이션
- [ ] JWT + 카카오/네이버/Google OAuth2
- [ ] Redis 연동 (캐시, 세션, Rate Limit)
- [ ] API CRUD (사용자, 보고서 목록/상세)

### Phase 1-B: 파이프라인 통합 (5-6주차)

- [ ] Python Worker: Redis Stream 컨슈머
- [ ] Go 보고서 엔드포인트 + SSE 진행률
- [ ] PDF 생성 (weasyprint/reportlab)
- [ ] Cloud Storage 업로드
- [ ] Toss Payments 결제 통합 (카드/네이버페이/카카오페이)

### Phase 1-C: 프론트엔드 (7-8주차)

- [ ] Next.js + Tailwind CSS
- [ ] 랜딩, 가격 (SSG)
- [ ] 인증 UI (소셜 로그인 3사)
- [ ] 대시보드, 인터뷰 플로우, 보고서 뷰어
- [ ] 결제 UI (Toss 위젯)

### Phase 1-D: 통합 & 출시 (9-10주차)

- [ ] 사용자 프로필, 이용 내역
- [ ] 모바일 반응형 최적화
- [ ] staging QA → production 출시

**MVP 출시: 10주차 (2.5개월)**

### Phase 2: Android (11-18주차, +2개월)

- [ ] React Native — 동일 REST API
- [ ] 네이티브 소셜 로그인 (카카오/네이버/Google)
- [ ] 보고서 완료 푸시 (FCM)
- [ ] Toss Payments 모바일 SDK

### Phase 3: iOS (19-28주차, +2.5개월)

- [ ] React Native iOS 빌드 (또는 SwiftUI)
- [ ] Apple Sign-In (App Store 필수)
- [ ] App Store 심사 (2-3주 여유)

---

## 12. 핵심 참조 파일

| 파일 | 역할 | 활용 |
|------|------|------|
| `codes/report/orchestrator.py` | 보고서 생성 파이프라인 | Python Worker에서 래핑 |
| `codes/report/config/params.yaml` | 전체 설정 | Secret Manager 마이그레이션 |
| `codes/api/base.py` | API 클라이언트 베이스 | Go 재구현 참조 |
| `codes/generation/llm_client.py` | LLM 듀얼 모드 | Worker에서 API 모드 사용 |
| `codes/report/interview.py` | 4단계 인터뷰 | React 폼 위자드 참조 |
| `codes/report/charts.py` | matplotlib 차트 | Worker 유지 |
| `codes/rules/engine.py` | 세금/대출 룰엔진 | Worker 유지 |
| `codes/query/pipeline.py` | RAG 검색 | gRPC 서비스 노출 |
| `docker/docker-compose.yml` | 현 로컬 인프라 | K8s 매니페스트 참조 |

---

## 13. 검증 계획

- [ ] 10개 골든 주소 E2E (주소→결제→보고서→PDF)
- [ ] 부하 테스트: k6/Locust 동시 50 보고서, API p95 < 500ms
- [ ] 보안: OWASP ZAP, SQL Injection/XSS
- [ ] 결제: Toss 테스트 모드 전체 플로우 (카드/네이버페이/카카오페이)
- [ ] 모바일: iOS Safari, Android Chrome 실기기
- [ ] 모니터링: P0/P1 알림 발화 테스트
- [ ] PIPA: 개인정보 동의, 열람/삭제 API
- [ ] 장애복구: Cloud SQL 장애 조치, Redis 재시작 후 큐 복구
