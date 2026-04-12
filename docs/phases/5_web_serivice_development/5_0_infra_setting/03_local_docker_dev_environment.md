# 로컬 Docker 개발 환경 설정 가이드

> 프로덕션 GKE 아키텍처를 로컬 Docker Compose로 미러링  
> 클라우드 비용 $0으로 전체 스택 개발  
> 최종 업데이트: 2026-04-06

---

## 0. 프로덕션 ↔ 로컬 핵심 대응표

| GCP 프로덕션 | 로컬 Docker | 왜 대체 가능한지 |
|-------------|-----------|----------------|
| **Cloud SQL** PostgreSQL 15 + PostGIS | `postgis/postgis:15-3.4` | 동일 DB 엔진 + 동일 확장. SQL, 스키마, 쿼리가 100% 동일하게 동작 |
| **Memorystore** Redis 7.2 | `redis:7.2-alpine` | 동일 Redis 버전. Streams, Pub/Sub, LRU 정책 모두 동일 |
| **GKE StatefulSet** Qdrant | `qdrant/qdrant:v1.17.0` | 동일 바이너리. 프로덕션과 완전히 같은 벡터 검색 동작 |
| **Cloud Storage** (버킷 2개) | `minio/minio:latest` | S3 호환 API. 파일 업로드/다운로드 코드가 거의 동일 |
| **GKE Deployment** Go API (2-10 Pod) | `golang:1.24-bookworm` + air | 동일 Go 버전. 차이: 로컬은 1개 인스턴스, Hot Reload 지원 |
| **GKE Deployment** Python Worker (1-8 Pod) | `python:3.12-slim` | 동일 Python 버전. 기존 codes/ 그대로 사용 |
| **Cloud CDN + Cloud Run** Next.js | `node:20-alpine` | 동일 Node.js. 차이: 로컬은 개발 서버, 프로덕션은 빌드된 정적 파일 |
| **GKE Deployment** Embedding + T4 GPU | `python:3.12-slim` (CPU) | 동일 모델(BGE-M3). CPU 모드: 단건 쿼리 ~200-500ms (개발 충분) |
| **VPC** (Private IP, NAT) | Docker network (bridge) | 서비스명으로 통신 (postgres:5432). 프로덕션도 K8s Service명 사용 |
| **Secret Manager** | `.env` 파일 | 로컬에서는 파일, 프로덕션에서는 API로 읽기. 코드 내 환경변수 참조는 동일 |

---

## 1. 개념 이해 — Docker Compose가 뭘 하는 건가

### 1.1 문제 상황

우리 서비스는 **8개의 프로그램**이 서로 통신하며 동작합니다:

```
사용자 브라우저
    ↓ HTTP
[Next.js 프론트엔드]
    ↓ HTTP REST API
[Go API 서버]
    ├── 읽기/쓰기 → [PostgreSQL DB]
    ├── 캐시 조회 → [Redis]
    ├── 작업 발행 → [Redis Streams]
    └── 파일 저장 → [MinIO/Cloud Storage]
         ↓ Redis Streams 소비
    [Python Worker]
    ├── 벡터 검색 → [Qdrant]
    ├── 임베딩 요청 → [Embedding 서버]
    ├── LLM 호출 → [Claude API]
    └── 결과 저장 → [PostgreSQL] + [MinIO]
```

이 8개를 각각 설치하고, 포트를 맞추고, 서로 연결하는 건 매우 번거롭습니다.
Docker Compose는 이 **8개를 한 번에 정의하고, 한 명령으로 전부 시작/정지**하는 도구입니다.

### 1.2 핵심 개념

**Docker 컨테이너란?**

> 프로그램 + 실행 환경을 하나의 격리된 상자에 넣은 것.

내 컴퓨터에 PostgreSQL을 직접 설치하면, 설정 파일이 시스템 곳곳에 흩어지고 버전 충돌이 생깁니다.
Docker 컨테이너는 PostgreSQL을 "상자" 안에 넣어서, 내 시스템과 완전히 분리된 채 실행합니다.
상자를 버리면(컨테이너 삭제) 흔적이 남지 않습니다.

**비유:** 각 프로그램을 개별 가상 컴퓨터에서 실행하는 것. 하지만 가상 머신(VM)보다 훨씬 가볍고 빠름.

**Docker Compose란?**

> 여러 컨테이너를 하나의 YAML 파일에 정의하고, 한 번에 관리하는 도구.

`docker-compose.yml`에 "PostgreSQL은 이 이미지, 이 포트, Redis는 이 이미지, 이 포트..."를 적어두면,
`docker compose up -d` 한 명령으로 전부 시작됩니다.

**Docker 네트워크란?**

> 컨테이너들이 서로를 **이름으로** 찾을 수 있게 해주는 가상 네트워크.

같은 Docker 네트워크(`realtor-dev-net`)에 속한 컨테이너들은,
`postgres:5432`처럼 **서비스 이름을 호스트명으로** 사용하여 통신합니다.
이것은 프로덕션에서 Kubernetes Service가 `postgres-service:5432`로 통신하는 것과 동일한 패턴입니다.

**Docker 볼륨이란?**

> 컨테이너가 삭제되어도 데이터가 유지되는 저장 공간.

컨테이너는 기본적으로 "일시적" — 삭제하면 안에 저장된 모든 데이터가 사라집니다.
DB 데이터처럼 보존해야 하는 것은 **볼륨**에 저장합니다.
볼륨은 호스트(내 컴퓨터)의 특정 위치에 실제 파일로 존재하며,
컨테이너를 삭제하고 다시 만들어도 같은 볼륨을 연결하면 데이터가 그대로 있습니다.

**비유:** USB 외장하드. 컴퓨터(컨테이너)를 포맷해도 USB(볼륨)의 데이터는 유지됨.

**헬스체크(Healthcheck)란?**

> Docker가 주기적으로 "이 컨테이너가 정상인지" 확인하는 검사.

PostgreSQL 컨테이너가 시작되어도, 실제로 접속을 받을 준비가 되기까지 몇 초 걸립니다.
헬스체크는 `pg_isready` 같은 명령을 주기적으로 실행해서, "아직 준비 안 됨" / "준비 완료"를 판단합니다.
다른 서비스(Go API)는 PostgreSQL의 헬스체크가 "준비 완료"가 되어야 시작합니다.

**프로덕션에서의 대응:** Kubernetes의 readinessProbe / livenessProbe가 같은 역할.

---

## 2. 파일 구조

```
codes/local-infra/
├── docker-compose.yml        # 8개 서비스 정의 (이 문서의 핵심)
├── .env.example              # 환경변수 템플릿 (비밀번호, 경로 등)
├── .env                      # 실제 환경변수 (git에 포함하지 않음)
├── .gitignore                # .env 등 민감 파일 제외
├── README.md                 # 빠른 시작 가이드
├── postgres/
│   └── init.sql              # DB 초기화 (PostGIS 확장 + 테이블 + 인덱스)
├── minio/
│   └── init.sh               # MinIO 버킷 초기 생성 (reports, static)
└── placeholder/              # 레포 미생성 시 대기용 빈 디렉토리
    ├── go-api/.gitkeep
    └── frontend/.gitkeep
```

---

## 3. 환경 설정

### 3.1 사전 요구사항

| 도구 | 최소 버전 | 확인 명령 | 설치 |
|------|----------|----------|------|
| Docker Engine | 24.0+ | `docker --version` | https://docs.docker.com/engine/install/ |
| Docker Compose | v2.20+ | `docker compose version` | Docker Engine에 포함 |
| (선택) NVIDIA Container Toolkit | — | `nvidia-smi` | GPU 임베딩 사용 시만 |

> **Docker Engine vs Docker Desktop:**  
> Docker Engine은 리눅스 전용 CLI 도구.  
> Docker Desktop은 Windows/Mac에서 GUI + Engine을 함께 제공하는 앱.  
> 우리 환경(Ubuntu)에서는 Docker Engine만으로 충분합니다.

### 3.2 초기 설정 (1회)

```bash
cd /home/gon/ws/rag/codes/local-infra

# 1. 환경변수 파일 생성
cp .env.example .env

# 2. .env 파일 열어서 경로 확인/수정
#    - QDRANT_STORAGE_PATH: 기존 Qdrant 데이터 경로
#    - PYTHON_WORKER_SRC_PATH: RAG 프로젝트 루트
#    - HF_CACHE_PATH: HuggingFace 모델 캐시 경로
#    (기본값이 현재 환경에 맞게 설정되어 있으므로 변경 불필요할 수 있음)
```

### 3.3 서비스 시작

```bash
# 방법 1: 인프��� 서비스만 먼저 (추천 — 리소스 절약)
docker compose up -d postgres redis qdrant minio minio-init

# 방법 2: 전체 서비스 한번에
docker compose up -d

# 상태 확인
docker compose ps

# 기대 출력:
# NAME                  STATUS          PORTS
# realtor-postgres      Up (healthy)    0.0.0.0:5432->5432/tcp
# realtor-redis         Up (healthy)    0.0.0.0:6379->6379/tcp
# realtor-qdrant        Up (healthy)    0.0.0.0:6333->6333/tcp, ...
# realtor-minio         Up (healthy)    0.0.0.0:9000->9000/tcp, ...
# realtor-minio-init    Exited (0)      (정상 — 1회성 초기화 후 종료)
```

---

## 4. 서비스 상세 설명

### 4.1 PostgreSQL + PostGIS — 관계형 데이터베이스

**프로���션 대응:** Cloud SQL (`db-custom-2-7680`: 2 vCPU, 7.5GB RAM, 20GB SSD, Private IP)

**역할:** 사용자 정보, 보고서 기록, 결제 내역, API 응답 캐시 저장.
"구조화된 데이터"(표 형태로 정리할 수 있는 데이터)를 저장하고 SQL로 조회합니다.

**PostGIS란?** PostgreSQL의 확장(Extension). 위도/경도 같은 **공간 데이터**를 효율적으로 저장하고 검색합니다.
예: "강남역에서 반경 1km 이내의 모든 아파트를 찾아라" — 이런 쿼리를 빠르게 처리합니다.
프로덕션 Cloud SQL에서도 `CREATE EXTENSION postgis;`로 동일하게 활성화합니다.

**로컬 설정 상세:**

| 항목 | 값 | 프로덕션 대응 |
|------|-----|-------------|
| 이미지 | `postgis/postgis:15-3.4` | Cloud SQL PostgreSQL 15 |
| DB 이름 | `realtor_staging` | `realtor_staging` (동일) |
| 사용자 | `realtor_app` | `realtor_app` (동일) |
| 비밀번호 | `.env`에서 설정 | Secret Manager + 랜덤 32자 |
| 포트 | 5432 (기본) | Private IP:5432 (외부 접근 불가) |
| 볼륨 | `realtor-pgdata` (Named Volume) | 20GB PD_SSD (자동 확장) |
| 초기화 | `postgres/init.sql` | Cloud SQL에서 수동 또는 마이그레이션 도구 |

**초기화 스크립트 (`init.sql`)가 하는 일:**

1. PostGIS 확장 활성화
2. UUID 생성 함수 활성화
3. 5개 테이블 생성:
   - `users` — 사용자 (이메일/OAuth 로그인, 구독 티어)
   - `reports` — 보고서 (주소, 목적, 상태, PDF URL)
   - `report_sections` — 보고서 섹션 7개 (위치, 가격, 법률, 투자, 일조, 리스크, 미래)
   - `payments` — 결제 (Toss Payments 연동)
   - `api_cache` — 외부 API 응답 캐시 (PostGIS 공간 인덱스 포함)
4. 인덱스 생성 (검색 성능 최적화)

**접속 방법:**

```bash
# psql CLI로 접속
docker exec -it realtor-postgres psql -U realtor_app -d realtor_staging

# 테이블 목록 확인
\dt

# PostGIS 버전 확인
SELECT PostGIS_Version();

# 테이블 구조 확인
\d users
\d reports
```

**프로덕션과의 차이점:**

| 항목 | 로컬 | 프로덕션 |
|------|------|---------|
| 접속 방식 | 직접 TCP (localhost:5432) | Cloud SQL Auth Proxy (사이드카 컨테이너) |
| 인증 | 비밀번호 | IAM 인증 (서비스 계정) |
| 가용성 | 단일 인스턴스 | REGIONAL (자동 장애 복구) |
| 백업 | 없음 (필요 시 `pg_dump`) | 매일 자동, 7일 보관 |
| 네트워크 | 호스트에서 접근 가능 | VPC 내부에서만 접근 (Private IP) |

---

### 4.2 Redis — 인메모리 캐시 + 메시지 큐

**프로덕션 대응:** Memorystore (1GB BASIC, Redis 7.2, `allkeys-lru`)

**역할 (3가지):**

1. **캐시(Cache):** 외부 API 응답을 일시 저장. 같은 아파트의 실거래가를 5분 내에 또 조회하면, API를 다시 호출하지 않고 Redis에서 바로 가져옴 → 속도 향상 + API 호출 횟수 절약

2. **메시지 큐(Message Queue) — Redis Streams:**
   Go API가 "이 주소의 보고서를 만들어줘"라는 **작업(Job)**을 Redis Streams에 넣으면,
   Python Worker가 이 작업을 가져가서(consume) 보고서를 생성.
   **비유:** 음식점의 주문 전표 시스템. 홀(Go API)이 주문서를 걸면, 주방(Worker)이 순서대로 가져가 조리.

3. **실시간 진행 상태 전송 — Redis Pub/Sub:**
   Worker가 보고서 생성 중에 "Section 3/7 완료" 같은 진행 상태를 Redis에 `PUBLISH`.
   Go API가 `SUBSCRIBE`하고 있다가 SSE(Server-Sent Events)로 프론트엔드에 전달.

**Redis Streams란?**

> Redis에 내장된 메시지 큐. 작업을 순서대로 저장하고, 여러 소비자(Worker)가 나눠 가져갈 수 있음.

일반 Redis의 `SET key value`는 단순 저장이지만,
Streams는 `XADD` (작업 추가), `XREADGROUP` (소비자 그룹에서 작업 가져가기), `XACK` (완료 확인) 같은
메시지 큐 전용 명령을 제공합니다.

프로덕션에서 별도의 메시지 큐(RabbitMQ, Kafka)를 쓰지 않고 Redis Streams를 선택한 이유:
- 이미 캐시용으로 Redis를 쓰고 있으므로 추가 인프라 불필요
- 일일 300-8,000건 보고서 규모에서는 Redis Streams로 충분

**로컬 설정 상세:**

| 항목 | 값 | 프로덕션 대응 |
|------|-----|-------------|
| 이미지 | `redis:7.2-alpine` | Memorystore Redis 7.2 |
| 최대 메모리 | 512MB | 1GB (BASIC) → 5GB (STANDARD_HA) |
| 메모리 정책 | `allkeys-lru` | `allkeys-lru` (동일) |
| 데이터 지속성 | AOF (appendonly) | Memorystore 자동 관리 |
| 포트 | 6379 | Private IP:6379 |

> **allkeys-lru란?**  
> LRU = Least Recently Used (가장 오래 전에 사용된 것).  
> 메모리가 가득 차면, 가장 오래 접근하지 않은 키를 자동으로 삭제해서 공간을 확보합니다.  
> 캐시용으로 적합한 정책 — 자주 조회되는 데이터는 유지, 안 쓰는 데이터는 자동 정리.

**접속 방법:**

```bash
# redis-cli로 접속
docker exec -it realtor-redis redis-cli

# 상태 확인
INFO server
INFO memory

# 저장된 키 목록 (개발 시)
KEYS *

# Streams 확인 (Worker 구현 후)
XINFO STREAM report_jobs
XINFO GROUPS report_jobs
```

---

### 4.3 Qdrant — 벡터 데이터베이스

**프로덕션 대응:** GKE StatefulSet (20Gi PVC, 1→3 replicas)

**역할:** 11,035개 부동산 전문가 영상 스크립트를 **벡터(숫자 배열)**로 변환하여 저장하고,
사용자 질문과 **의미적으로 유사한** 문서를 검색합니다 (RAG — Retrieval Augmented Generation).

**벡터 검색이 뭔가?**

일반 DB는 키워드 일치로 검색합니다. "강남 아파트 전세" → "강남", "아파트", "전세"가 포함된 문서를 찾음.
벡터 검색은 **의미(뜻)**가 비슷한 문서를 찾습니다.

작동 원리:
1. 텍스트를 **임베딩 모델**(BGE-M3)에 넣으면 1024개의 숫자 배열(벡터)이 나옴
2. 의미가 비슷한 텍스트는 비슷한 숫자 배열을 가짐
3. "갭투자"와 "전세끼고 매매"는 키워드는 다르지만, 벡터는 거의 같음
4. 사용자 질문을 벡터로 변환 → 저장된 모든 벡터와 거리 비교 → 가장 가까운 것 반환

**비유:** 도서관에서 제목이 아닌 "내용의 뜻"으로 책을 찾는 것.

**로컬 설정 상세:**

| 항목 | 값 | 프로덕션 대응 |
|------|-----|-------------|
| 이미지 | `qdrant/qdrant:v1.17.0` | 동일 |
| 데이터 | 호스트 마운트 (`qdrant_storage/`, 5.3GB) | PVC 20Gi |
| 컬렉션 | `realestate_v2` (93,943 포인트), `domain_ontology_v2` (2,146), `legal_docs_v2` (976) | 동일 데이터 |
| REST 포트 | 6333 | 6333 (K8s Service) |
| gRPC 포트 | 6334 | 6334 (K8s Service) |

> **중요:** `QDRANT_STORAGE_PATH`는 기존 `docker/docker-compose.yml`의 Qdrant와 같은 데이터를 가리킵니다.
> **동시에 두 Qdrant 컨테이너가 같은 스토리지를 마운트하면 데이터 손상이 발생할 수 있습니다.**
> 기존 `rag-qdrant` 컨테이너를 먼저 중지하세요: `docker stop rag-qdrant`

**접속 방법:**

```bash
# REST API로 컬렉션 목록 확인
curl http://localhost:6333/collections

# 특정 컬렉션 정보
curl http://localhost:6333/collections/realestate_v2

# 포인트 개수 확인
curl http://localhost:6333/collections/realestate_v2 | python3 -m json.tool | grep points_count
```

---

### 4.4 MinIO — S3 호환 오브젝트 스토리지

**프로덕션 대응:** Cloud Storage (`realtor-staging-reports`, `realtor-staging-static`)

**역할:** 생성된 PDF 보고서와 차트 이미지를 파일로 저장하고, URL로 다운로드 가능하게 제공.

**오브젝트 스토리지란?**

> 파일을 저장하고 URL로 접근하는 저장소. 일반 파일시스템과 다르게, 폴더 구조 없이 **키(Key)**로 파일을 관리.

예: `reports/2026/04/abc123.pdf` → 이것은 폴더가 아니라 하나의 키(이름)일 뿐.
클라우드 스토리지(AWS S3, GCP Cloud Storage)는 모두 이 방식.

**MinIO란?** S3 API와 호환되는 오픈소스 오브젝트 스토리지. 로컬에서 Cloud Storage를 대체할 수 있음.

**버킷(Bucket)이란?** 파일을 담는 최상위 컨테이너. USB 드라이브처럼 파일들을 묶어서 관리하는 단위.

| 버킷 | 용도 | 프로덕션 대응 |
|------|------|-------------|
| `realtor-reports` | PDF 보고서, 차트 이미지 | `gs://realtor-staging-reports` (1년→NEARLINE, 3년→COLDLINE 자동 아카이브) |
| `realtor-static` | Next.js 정적 자산 (HTML, CSS, JS) | `gs://realtor-staging-static` (웹사이트 호스팅) |

**MinIO 웹 콘솔:**

```
URL: http://localhost:9001
ID:  minioadmin
PW:  minioadmin123
```

브라우저에서 접속하면 버킷 목록, 파일 업로드/다운로드, 사용량 등을 GUI로 관리할 수 있습니다.

**프로덕션과의 차이점:**

| 항목 | 로컬 (MinIO) | 프로덕션 (Cloud Storage) |
|------|-------------|----------------------|
| API | S3 호환 (boto3, minio-go) | GCS 네이티브 SDK (`cloud.google.com/go/storage`) |
| 다운로드 URL | `http://localhost:9000/realtor-reports/file.pdf` | Signed URL (4시간 만료, 인증 필요) |
| 권한 | 공개 다운로드 (개발용) | IAM 기반 접근 제어 |
| 생명주기 | 없음 | 자동 아카이브 (1년→NEARLINE, 3년→COLDLINE) |

> **코드 전환 전략:** Go API에서 스토리지 접근을 인터페이스로 추상화.  
> `StorageClient` 인터페이스에 `Upload()`, `GetURL()` 메서드를 정의하고,  
> `MinIOClient` (로컬)와 `GCSClient` (프로덕션) 두 구현체를 만듦.  
> 환경변수 `STORAGE_BACKEND=minio|gcs`로 전환.

---

### 4.5 Go API 서버 — REST API + 인증 + 작업 발행

**프로덕션 대응:** GKE Deployment (2-10 replicas, HPA by CPU/Memory)

**역할:** 프론트엔드와 통신하는 **중앙 API 서버**.

| 기능 | 설명 |
|------|------|
| 인증 | JWT 토큰 발행/검증, OAuth2 소셜 로그인 (Kakao, Naver, Google) |
| 사용자 관리 | 회원가입, 프로필, 구독 티어 |
| 보고서 관리 | 보고서 생성 요청 → Redis Streams에 작업 발행 → 상태 조회 |
| SSE 스트리밍 | 보고서 생성 진행 상태를 실시간으로 프론트엔드에 전송 |
| 결제 | Toss Payments API 연동 (승인, 취소, 웹훅) |
| 주소 정규화 | Kakao Geocoding API로 주소 → 좌표/법정동코드 변환 |

**Hot Reload (air) 란?**

Go 코드를 수정하면 **자동으로 재컴파일 + 재시작**됩니다.
매번 `go build` → 서버 재시작을 수동으로 할 필요 없음.
`air`는 Go용 Hot Reload 도구로, 파일 변경을 감지하여 자동 처리합니다.

**비유:** Next.js의 Fast Refresh, Python의 `--reload` 플래그와 같은 개념.

**현재 상태:** `realtor-ai-backend` GitHub 레포가 아직 미생성.
레포 생성 후 `.env`에서 `GO_API_SRC_PATH`를 설정하면 자동으로 `air`가 동작합니다.
레포 미생성 시에는 대기 모드(placeholder)로 실행되어 자원을 거의 사용하지 않습니다.

**환경변수 (Go API → 다른 서비스 연결):**

```
DATABASE_URL=postgresql://realtor_app:localdev@postgres:5432/realtor_staging?sslmode=disable
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
STORAGE_ENDPOINT=http://minio:9000
```

> `postgres`, `redis`, `qdrant`, `minio`는 Docker Compose의 서비스 이름.
> Docker 네트워크 안에서 이 이름이 **자동으로 해당 컨테이너의 IP로 변환**됩니다.
> 프로덕션에서는 `postgres` 대신 Cloud SQL Auth Proxy의 localhost 주소가 들어갑니다.

---

### 4.6 Python Worker — 보고서 생성 워커

**프로덕션 대응:** GKE Deployment (1-8 replicas, HPA by Redis queue depth)

**역할:** Redis Streams에서 보고서 생성 작업을 가져와서, 실제 보고서를 생성하는 **백그라운드 작업자**.

**작동 흐름:**

```
1. Go API가 Redis Streams에 작업 추가:
   XADD report_jobs * address "마포래미안푸르지오" purpose "매매_실거주"

2. Python Worker가 작업 가져가기:
   XREADGROUP GROUP workers consumer1 COUNT 1 BLOCK 5000 STREAMS report_jobs >

3. 보고서 생성 파이프라인 실행:
   a. 주소 정규화 (Kakao API)
   b. 13개 외부 API 병렬 호출 (실거래가, 건축물대장, KOSIS 등)
   c. 정책 룰엔진 (세금, 대출 한도 계산)
   d. 7개 섹션 LLM 생성 (Claude, 최대 3개 병렬)
   e. 차트 생성 (matplotlib)
   f. PDF 조립 + MinIO 업로드

4. 진행 상태 실시간 전송:
   PUBLISH report:progress:abc123 '{"section": 3, "total": 7, "status": "generating"}'

5. 완료 후:
   - PostgreSQL에 보고서 메타데이터 저장
   - Redis Streams에서 작업 확인: XACK report_jobs workers {message_id}
```

**로컬 설정 상세:**

| 항목 | 값 | 프로덕션 대응 |
|------|-----|-------------|
| 이미지 | `python:3.12-slim` | 커스텀 이미지 (requirements.txt 기반) |
| 소스코드 | `/home/gon/ws/rag` 전체 마운트 | Docker 이미지에 코드 내장 (COPY) |
| PYTHONPATH | `/workspace/codes` | 동일 |
| LLM 백엔드 | `cli` (Claude Code, 무료) | `api` (Anthropic SDK, 유료) |

> **LLM 백엔드 전환:**
> `codes/generation/llm_client.py`의 `create_llm_client()` 함수가
> 환경변수 `LLM_BACKEND`를 읽어서 CLI 모드 / API 모드를 자동 선택합니다.
> 로컬에서는 `cli` (무료), 프로덕션에서는 `api` (유료)를 사용합니다.

**현재 상태:** 기존 `codes/report/orchestrator.py`가 보고서 생성 파이프라인의 핵심.
Redis Streams 소비자 래퍼 코드가 구현되면 이 컨테이너에서 실행됩니다.
현재는 대기 모드로, `docker exec -it realtor-python-worker bash`로 접속하여 기존 코드를 직접 테스트할 수 있습니다.

---

### 4.7 Next.js 프론트엔드 — 사용자 웹 인터페이스

**프로덕션 대응:** Cloud CDN + Cloud Storage (정적) / Cloud Run (SSR)

**역할:** 사용자가 브라우저에서 보는 웹 페이지. 주소 입력 → 인터뷰 → 보고서 생성 → 보고서 뷰어.

**주요 페이지:**

| 페이지 | 타입 | 설명 |
|--------|------|------|
| 랜딩 (`/`) | SSG | 서비스 소개 (정적) |
| 로그인 (`/login`) | CSR | Kakao/Naver/Google OAuth |
| 대시보드 (`/dashboard`) | CSR | 보고서 목록, 생성 버튼 |
| 보고서 생성 (`/report/new`) | CSR | 주소 입력 → 인터뷰 4단계 → 생성 시작 |
| 보고서 진행 (`/report/[id]/progress`) | CSR + SSE | 실시간 진행 바 (7개 섹션) |
| 보고서 보기 (`/report/[id]`) | CSR | 7개 섹션 + 차트 + PDF 다운로드 |
| 결제 (`/pricing`) | CSR | 구독 플랜 + Toss Payments |

> **SSG vs CSR:**
> - **SSG (Static Site Generation):** 빌드 시 HTML을 미리 생성. 내용이 거의 바뀌지 않는 페이지.
> - **CSR (Client-Side Rendering):** 브라우저에서 JavaScript가 실행되며 동적으로 페이지 구성. 로그인, 데이터 조회 등.

> **SSE (Server-Sent Events):**
> 서버가 클라이언트에게 **일방향으로 실시간 데이터를 보내는** 기술.
> WebSocket과 비슷하지만 더 단순 — 서버→클라이언트 방향만.
> 보고서 생성 진행 상태를 "Section 1/7 완료 → 2/7 → ... → 7/7 완료"처럼 실시간 전달.

**현재 상태:** `realtor-ai-frontend` GitHub 레포가 아직 미생성.
레포 생성 후 `.env`에서 `FRONTEND_SRC_PATH`를 설정하면 `npm run dev`가 자동 실행됩니다.

**환경변수:**

```
NEXT_PUBLIC_API_URL=http://localhost:8080   # Go API 서버 주소
NEXT_PUBLIC_STORAGE_URL=http://localhost:9000  # MinIO (이미지/PDF 다운로드)
```

> `NEXT_PUBLIC_` 접두사: Next.js에서 **브라우저에서도 접근 가능한** 환경변수.
> 접두사 없는 환경변수는 서버 사이드에서만 접근 가능 (비밀 정보 보호).

---

### 4.8 임베딩 서버 — 텍스트 → 벡터 변환

**프로덕션 대응:** GKE Deployment + T4 GPU (12시간/일 운영)

**역할:** 텍스트를 벡터(숫자 배열)로 변환하는 전용 서버.
Go API나 Python Worker가 "이 텍스트를 벡터로 바꿔줘"라고 HTTP 요청을 보내면,
BGE-M3 모델이 1024차원 벡터를 반환합니다.

**왜 별도 서버인가?**

임베딩 모델(BGE-M3)은 크기가 약 2GB. 이것을 Go API에 넣을 수 없고(Go는 Python ML 라이브러리 미지원),
Python Worker에 직접 넣으면 Worker가 여러 개일 때 모델이 중복 로드됩니다.
별도 서버로 분리하면 모든 서비스가 공유할 수 있어 메모리 효율적입니다.

**로컬 성능:**

| 모드 | 단건 쿼리 | 1,000건 배치 | 사용 시기 |
|------|----------|------------|----------|
| CPU (기본) | ~200-500ms | ~5-10분 | 일상 개발 (검색 테스트) |
| GPU (NVIDIA) | ~20-50ms | ~30초 | 대량 인덱싱, 벤치마크 |

> 이미 93,943 포인트가 Qdrant에 인덱싱되어 있으므로,
> 일상 개발에서는 CPU 모드의 단건 임베딩(~200-500ms)으로 충분합니다.

**현재 상태:** FastAPI 기반 임베딩 서버 코드가 구현되면 이 컨테이너에서 실행됩니다.
현재는 대기 모드. 기존 `docker/docker-compose.yml`의 `rag-embedding` 컨테이너가
GPU 기반 임베딩을 수행하고 있으며, 이 서비스는 프로덕션 아키텍처에 맞춘 독립 서버 형태입니다.

---

## 5. 서비스 간 네트워크 통신

### 5.1 네트워크 구조

모든 컨테이너가 하나의 Docker 네트워크(`realtor-dev-net`)에 연결됩니다.

```
                       realtor-dev-net (Docker bridge network)
                       ─────────────────────────────────────────
                       │                                       │
  [호스트 브라우저]     │    ┌──────────────────────┐           │
  localhost:3000 ──────┼───>│  frontend (:3000)     │           │
                       │    └──────────┬───────────┘           │
                       │               │ HTTP                   │
                       │    ┌──────────▼───────────┐           │
  localhost:8080 ──────┼───>│  go-api (:8080)       │           │
                       │    └─────┬──────┬────┬────┘           │
                       │          │      │    │                 │
                       │          │      │    │ XADD            │
                       │    ┌─────▼──┐ ┌─▼──┐ ┌▼────────────┐ │
                       │    │postgres│ │redis│ │ minio        │ │
                       │    │ :5432  │ │:6379│ │ :9000/:9001  │ │
                       │    └────────┘ └──┬──┘ └─────────────┘ │
                       │                  │ XREADGROUP          ��
                       │    ┌─────────────▼──────────┐         │
                       │    │  python-worker          │         │
                       │    └──────┬──────┬──────────┘         │
                       │           │      │                     │
                       │    ┌──────▼──┐ ┌─▼──────────┐         │
                       │    │ qdrant  │ │ embedding   │         │
                       │    │ :6333   │ │ :8001       │         │
                       │    └─────────┘ └─────────────┘         │
                       ─────────────────────────────────────────
```

### 5.2 통신 방식

| 출발 | 도착 | 프로토콜 | 용도 |
|------|------|---------|------|
| 브라우저 | frontend:3000 | HTTP | 웹 페이지 로딩 |
| frontend | go-api:8080 | HTTP REST | API 호출 (프론트엔드에서는 `localhost:8080`으로 접근) |
| go-api | postgres:5432 | TCP (PostgreSQL 프로토콜) | SQL 쿼리 실행 |
| go-api | redis:6379 | TCP (RESP 프로토콜) | 캐시 읽기/쓰기, 세션, 작업 발행 |
| go-api | minio:9000 | HTTP (S3 API) | PDF/이미지 업로드, 다운로드 URL 생성 |
| python-worker | redis:6379 | TCP | 작업 소비 (XREADGROUP), 진행 상태 전송 (PUBLISH) |
| python-worker | postgres:5432 | TCP | 보고서 메타데이터 저장 |
| python-worker | qdrant:6333 | HTTP (REST) 또는 gRPC (:6334) | RAG 벡터 검색 |
| python-worker | embedding:8001 | HTTP | 텍스트 → 벡터 변환 |
| python-worker | minio:9000 | HTTP (S3 API) | PDF/차트 이미지 업로드 |
| python-worker | (외부) | HTTP | Claude API, data.go.kr, Kakao Maps 등 |

### 5.3 호스트에서 접근 가능한 포트

Docker Compose의 `ports` 설정으로 호스트(내 컴퓨터)에서도 접근 가능:

| URL | 서비스 | 용도 |
|-----|--------|------|
| `http://localhost:3000` | Next.js | 웹 프론트엔드 |
| `http://localhost:8080` | Go API | API 테스트 (curl, Postman) |
| `http://localhost:5432` | PostgreSQL | DB 클라이언트 (DBeaver, pgAdmin) |
| `http://localhost:6379` | Redis | Redis 클라이언트 |
| `http://localhost:6333` | Qdrant | REST API, 대시보드 |
| `http://localhost:9000` | MinIO API | S3 API 직접 호출 |
| `http://localhost:9001` | MinIO 콘솔 | 웹 GUI 파일 관리 |
| `http://localhost:8001` | 임베딩 서버 | 임베딩 API 테스트 |

---

## 6. 환경변수 관리

### 6.1 `.env.example` → `.env` 복사

```bash
cp .env.example .env
```

`.env.example`은 Git에 포함 (기본값/구조 공유용).
`.env`는 `.gitignore`에 등록되어 Git에 포함되지 않음 (비밀번호, API 키 보호).

### 6.2 핵심 환경변수 그룹

| 그룹 | 변수 | 로컬 기본값 | 프로덕션 |
|------|------|-----------|---------|
| **DB** | `DATABASE_URL` | `postgresql://...@postgres:5432/...` | Cloud SQL Auth Proxy 경유 |
| **캐시** | `REDIS_URL` | `redis://redis:6379/0` | Memorystore Private IP |
| **스토리지** | `STORAGE_ENDPOINT` | `http://minio:9000` | `https://storage.googleapis.com` |
| **LLM** | `LLM_BACKEND` | `cli` (무료) | `api` (유료) |
| **인증** | `JWT_SECRET` | 개발용 고정 문자열 | Secret Manager에서 로드 |

### 6.3 프로덕션 전환 시 변경되는 환경변수

로컬 → 프로덕션 전환 시 **코드 변경 없이 환경변수만 바뀝니다:**

```bash
# 로컬
DATABASE_URL=postgresql://realtor_app:localdev@postgres:5432/realtor_staging?sslmode=disable
REDIS_URL=redis://redis:6379/0
STORAGE_ENDPOINT=http://minio:9000
LLM_BACKEND=cli

# 프로덕션 (K8s ConfigMap + Secret)
DATABASE_URL=postgresql://realtor_app@127.0.0.1:5432/realtor_staging?sslmode=disable  # Auth Proxy
REDIS_URL=redis://10.x.x.x:6379/0  # Memorystore Private IP
STORAGE_ENDPOINT=https://storage.googleapis.com
STORAGE_BACKEND=gcs
LLM_BACKEND=api
ANTHROPIC_API_KEY=sk-ant-...  # Secret Manager
```

---

## 7. 개발 워크플로우

### 7.1 일상적인 개발 사이클

```bash
# 1. 아침: 서비스 시작
cd /home/gon/ws/rag/codes/local-infra
docker compose up -d

# 2. 코드 수정 (IDE에서)
#    → Go API: air가 자동 재빌드
#    → Next.js: Fast Refresh 자동 반영
#    → Python: 컨테이너 재시작 또는 직접 실행

# 3. API 테스트
curl http://localhost:8080/api/v1/health
curl -X POST http://localhost:8080/api/v1/reports -H "Authorization: Bearer ..." -d '...'

# 4. DB 확인
docker exec -it realtor-postgres psql -U realtor_app -d realtor_staging -c "SELECT * FROM reports;"

# 5. 로그 확인
docker compose logs -f go-api python-worker

# 6. 퇴근: 서비스 중지 (데이터 유지)
docker compose down
```

### 7.2 DB 스키마 변경 시

```bash
# init.sql은 최초 1회만 실행됨
# 이미 데이터가 있는 상태에서 스키마를 변경하려면:

# 방법 1: 직접 ALTER TABLE 실행
docker exec -it realtor-postgres psql -U realtor_app -d realtor_staging -c "
  ALTER TABLE reports ADD COLUMN new_column TEXT;
"

# 방법 2: DB 초기화 (데이터 삭제 + init.sql 재실행)
docker compose down
docker volume rm realtor-pgdata
docker compose up -d postgres
# → init.sql이 다시 실행됨

# 방법 3 (추천 — Go 개발 시작 후): golang-migrate 사용
# migrations/ 폴더에 SQL 마이그레이션 파일 관리
```

### 7.3 Python Worker 코드 테스트

```bash
# 컨테이너 셸 접속
docker exec -it realtor-python-worker bash

# 기존 코드 실행 테스트
cd /workspace/codes
python -c "from report.orchestrator import ReportOrchestrator; print('import OK')"
python -c "from api.clients.kakao import KakaoClient; print('import OK')"
python -c "from rules.engine import RuleEngine; print('import OK')"

# 인터랙티브 테스트
python3
>>> from report.orchestrator import ReportOrchestrator
>>> # ...
```

### 7.4 기존 docker/docker-compose.yml과의 공존

기존 RAG 연구용 Compose(`docker/docker-compose.yml`)와 이 개발용 Compose는 **포트 충돌**이 있습니다:

| 포트 | 기존 (docker/) | 개발용 (local-infra/) |
|------|-------------|---------------------|
| 6333, 6334 | `rag-qdrant` | `realtor-qdrant` |
| 8000 | `rag-chatbot` | — (충돌 없음) |

**해결 방법:**

```bash
# 방법 1 (추천): 기존 컨테이너 중지 후 개발 환경 시작
cd /home/gon/ws/rag/docker
docker compose down
cd /home/gon/ws/rag/codes/local-infra
docker compose up -d

# 방법 2: .env에서 포트 변경
# QDRANT_REST_PORT=16333
# QDRANT_GRPC_PORT=16334
```

> **Qdrant 데이터 공유 주의:** 두 Compose 파일이 같은 `qdrant_storage/` 디렉토리를 마운트합니다.
> **동시에 두 Qdrant 컨테이너를 실행하면 데이터 손상 위험이 있습니다.**
> 항상 하나만 실행하세요.

---

## 8. 프로덕션 전환 시 변경 사항

로컬 Docker Compose → GKE 프로덕션으로 전환할 때 필요한 변경:

### 8.1 코드 변경이 필요한 항목

| 항목 | 로컬 | 프로덕션 | 변경 내용 |
|------|------|---------|---------|
| 스토리지 SDK | MinIO (S3 API) | GCS 네이티브 SDK | `StorageClient` 인터페이스 구현체 교체 |

> 이 외의 모든 변경은 **코드 수정 없이 설정(환경변수)만 교체**로 처리 가능합니다.

### 8.2 설정만 변경하는 항목

| 항목 | 로컬 → 프로덕션 변경 |
|------|---------------------|
| DB 연결 | `postgres:5432` → Cloud SQL Auth Proxy (127.0.0.1:5432) |
| Redis 연결 | `redis:6379` → Memorystore Private IP |
| LLM 백엔드 | `cli` → `api` (ANTHROPIC_API_KEY 추가) |
| JWT 시크릿 | 고정 문자열 → Secret Manager |
| CORS 도메인 | `localhost:3000` → `app.example.kr` |
| 로깅 | Docker stdout → Cloud Logging |

### 8.3 프로덕션에서만 추가되는 것

| 항목 | 설명 |
|------|------|
| Cloud SQL Auth Proxy | Go API, Python Worker Pod에 사이드카 컨테이너로 추가 |
| HPA (Horizontal Pod Autoscaler) | CPU/메모리/큐 깊이 기반 자동 스케일링 |
| Readiness/Liveness Probe | K8s가 Pod 상태를 주기적 검사 (로컬 Healthcheck의 프로덕션 버전) |
| Ingress + SSL + CDN | 외부 트래픽 수신, HTTPS, 정적 자산 캐싱 |
| PDB (Pod Disruption Budget) | 최소 가용 Pod 수 보장 (무중단 배포) |
| Network Policy | Pod 간 통신 제한 (예: 프론트엔드→DB 직접 접근 차단) |

---

## 9. 트러블슈팅

### 9.1 포트 충돌

```bash
# "port is already allocated" 에러 시
# 해당 포트를 사용 중인 프로세스 확인
sudo lsof -i :5432
# → 기존 PostgreSQL이 돌고 있으면 중지하거나, .env에서 포트 변경
# POSTGRES_PORT=15432
```

### 9.2 Qdrant 데이터 손상 방지

```bash
# 기존 rag-qdrant와 동시 실행 방지
docker ps | grep qdrant
# 두 개가 보이면 하나를 중지
docker stop rag-qdrant
```

### 9.3 PostgreSQL init.sql 재실행

```bash
# init.sql은 pgdata 볼륨이 비어있을 때만 실행됨
# 스키마를 바꾸고 처음부터 다시 하려면:
docker compose down
docker volume rm realtor-pgdata
docker compose up -d postgres
```

### 9.4 MinIO 버킷이 안 만들어질 때

```bash
# minio-init 로그 확인
docker compose logs minio-init

# 수동 재실행
docker compose run --rm minio-init
```

### 9.5 메모리 부족

8개 서비스를 모두 띄우면 메모리 사용량:

| 서비스 | 예상 메모리 |
|--------|-----------|
| PostgreSQL | ~200MB |
| Redis | ~50-100MB |
| Qdrant | ~500MB-1GB (데이터 크기에 비례) |
| MinIO | ~100MB |
| Go API | ~50-100MB |
| Python Worker | ~300-500MB |
| Next.js | ~200-300MB |
| Embedding (CPU) | ~2-3GB (모델 로드 시) |
| **합계** | **~3.5-5.5GB** |

> 메모리가 부족하면 인프라 서비스(postgres, redis, qdrant, minio)만 실행하고,
> 나머지는 필요할 때만 시작하세요.

---

## 10. 체크리스트

### 최초 설정 (1회)

- [ ] Docker Engine 24.0+ 설치 확인: `docker --version`
- [ ] Docker Compose v2.20+ 확인: `docker compose version`
- [ ] `.env.example` → `.env` 복사: `cp .env.example .env`
- [ ] `.env`에서 경로 확인 (QDRANT_STORAGE_PATH, PYTHON_WORKER_SRC_PATH 등)
- [ ] 기존 `rag-qdrant` 컨테이너 중지: `docker stop rag-qdrant`
- [ ] 인프라 서비스 시작: `docker compose up -d postgres redis qdrant minio minio-init`
- [ ] 헬스체크 확인: `docker compose ps` (모두 "Up (healthy)")
- [ ] PostgreSQL 접속 테스트: `docker exec -it realtor-postgres psql -U realtor_app -d realtor_staging -c '\dt'`
- [ ] Qdrant 컬렉션 확인: `curl http://localhost:6333/collections`
- [ ] MinIO 콘솔 접속: 브라우저에서 `http://localhost:9001`

### Go 백엔드 개발 시작 시

- [ ] `realtor-ai-backend` GitHub 레포 생성
- [ ] 레포 클론: `git clone ... ~/ws/realtor-ai-backend`
- [ ] `.env`에서 `GO_API_SRC_PATH` 주석 해제 + 경로 설정
- [ ] Go API 서비스 시작: `docker compose up -d go-api`
- [ ] 헬스체크 확인: `curl http://localhost:8080/health`

### Next.js 프론트엔드 개발 시작 시

- [ ] `realtor-ai-frontend` GitHub 레포 생성
- [ ] 레포 클론: `git clone ... ~/ws/realtor-ai-frontend`
- [ ] `.env`에서 `FRONTEND_SRC_PATH` 주석 해제 + 경로 설정
- [ ] 프론트엔드 서비스 시작: `docker compose up -d frontend`
- [ ] 브라우저에서 `http://localhost:3000` 접속 확인

---

## 11. 파일 위치 요약

| 파일 | 경로 | 용도 |
|------|------|------|
| Docker Compose | `codes/local-infra/docker-compose.yml` | 8개 서비스 정의 |
| 환경변수 템플릿 | `codes/local-infra/.env.example` | 기본값 + 구조 |
| DB 초기화 | `codes/local-infra/postgres/init.sql` | PostGIS + 5개 테이블 + 인덱스 |
| MinIO 초기화 | `codes/local-infra/minio/init.sh` | 버킷 2개 생성 |
| GCP 인프라 (대응) | `codes/realtor-ai-infra/terraform/` | 프로덕션 Terraform 모듈 |
| 기존 RAG Compose | `docker/docker-compose.yml` | Qdrant + 임베딩 (연구용) |
| GCP 도구 Compose | `codes/gcp_build/docker-compose.yaml` | Terraform/kubectl 컨테이너 |
