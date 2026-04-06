# Phase 0 인프라 설정 — 진행 현황 및 다음 단계

> 최종 업데이트: 2026-04-06

---

## 1. 완료된 항목

### 1.1 GCP 프로젝트 설정

| 항목 | 상태 | 비고 |
|------|------|------|
| GCP 계정 생성 | ✅ 완료 | y2gon3@gmail.com |
| 프로젝트 생성 | ✅ 완료 | `realtor-ai-prod` (Realtor AI Advisor) |
| 결제 계정 연결 | ✅ 완료 | `011A6B-81D052-8C1480` |
| gcloud CLI 설치 + 인증 | ✅ 완료 | Google Cloud SDK 563.0.0 |
| 프로젝트/리전 기본값 설정 | ✅ 완료 | `asia-northeast3` (서울) |
| ADC (Application Default Credentials) | ✅ 완료 | `gcloud auth application-default login` |

### 1.2 GCP Dev/Ops Docker 컨테이너

| 항목 | 상태 | 비고 |
|------|------|------|
| Dockerfile 작성 | ✅ 완료 | `codes/gcp_build/Dockerfile` |
| docker-compose.yaml 작성 | ✅ 완료 | `codes/gcp_build/docker-compose.yaml` |
| entrypoint.sh 작성 | ✅ 완료 | `codes/gcp_build/entrypoint.sh` |
| 이미지 빌드 + 테스트 | ✅ 완료 | `rag-gcp-dev:latest` (1.52GB, ARM64) |
| 호스트 GCP 인증 자동 전달 확인 | ✅ 완료 | `~/.config/gcloud` 볼륨 마운트 |

**컨테이너 포함 도구:**

| 도구 | 버전 |
|------|------|
| gcloud CLI | 563.0.0 |
| terraform | 1.11.4 |
| kubectl | 1.35.3 |
| gh (GitHub CLI) | 2.89.0 |
| Go | 1.24.2 |
| Node.js | 20.20.2 |
| Python 3 | 3.12.3 |

### 1.3 GCP 초기 설정 (init-gcp.sh)

| 항목 | 상태 | 비고 |
|------|------|------|
| GCP API 13개 활성화 | ✅ 완료 | container, sqladmin, redis, storage, compute 등 |
| Terraform 서비스 계정 | ✅ 완료 | `terraform-admin` + 13개 역할 |
| Go API 서비스 계정 | ✅ 완료 | `go-api-sa` (cloudsql.client, secretmanager, storage) |
| Python Worker 서비스 계정 | ✅ 완료 | `python-worker-sa` (cloudsql.client, secretmanager, storage) |
| Terraform 키 파일 | ✅ 완료 | `.secrets/terraform-key.json` |
| Artifact Registry | ✅ 완료 | `realtor-ai` (asia-northeast3, Docker) |
| Terraform 상태 버킷 | ✅ 완료 | `gs://realtor-ai-terraform-state` (버전 관리 활성) |
| GitHub CLI 인증 | ✅ 완료 | `gh auth login` |

### 1.4 Terraform 모듈 작성

| 항목 | 상태 | 비고 |
|------|------|------|
| 기본 구조 (versions, variables, main, outputs) | ✅ 완료 | |
| networking 모듈 (VPC, 서브넷, NAT, Private Service Access) | ✅ 완료 | |
| gke 모듈 (GKE Autopilot) | ✅ 완료 | |
| cloudsql 모듈 (PostgreSQL 15 + PostGIS) | ✅ 완료 | |
| memorystore 모듈 (Redis 7.2) | ✅ 완료 | |
| storage 모듈 (보고서 PDF, 정적 자산) | ✅ 완료 | |
| staging 환경 설정 | ✅ 완료 | |
| production 환경 설정 | ✅ 완료 | |
| `terraform init` 성공 | ✅ 완료 | GCS 백엔드 연결 확인 |
| `terraform plan` 성공 | ✅ 완료 | **14개 리소스 생성 예정, 에러 없음** |

### 1.5 GitHub 레포

| 레포 | 상태 | 비고 |
|------|------|------|
| `realtor-ai-infra` | ✅ 생성 + push 완료 | Terraform + K8s 인프라 코드 |
| `realtor-ai-backend` | ⬜ 미생성 | Go API 서버 |
| `realtor-ai-worker` | ⬜ 미생성 | Python 보고서 생성 워커 |
| `realtor-ai-frontend` | ⬜ 미생성 | Next.js 웹 프론트엔드 |

---

## 2. `terraform plan` 결과 — 생성 예정 리소스 (14개)

| # | 리소스 타입 | 이름 | 설명 |
|---|-----------|------|------|
| 1 | VPC Network | `realtor-staging` | 가상 네트워크 |
| 2 | Subnet | `realtor-staging-subnet` | 서울 리전 서브넷 (Pod/Service IP 포함) |
| 3 | Global Address | `realtor-staging-private-ip` | DB/Redis Private IP 대역 예약 |
| 4 | Service Networking | VPC Peering | Cloud SQL/Redis가 VPC 내부에서만 접근 |
| 5 | Router | `realtor-staging-router` | NAT 게이트웨이용 라우터 |
| 6 | Router NAT | `realtor-staging-nat` | 외부 API 호출용 (data.go.kr, Kakao 등) |
| 7 | GKE Cluster | `realtor-staging` | Autopilot, Private 노드, 서울 리전 |
| 8 | Cloud SQL Instance | `realtor-staging-db` | PostgreSQL 15, 2vCPU/7.5GB, SSD 20GB |
| 9 | SQL Database | `realtor_staging` | 기본 데이터베이스 |
| 10 | SQL User | `realtor_app` | 앱용 DB 사용자 (랜덤 32자 비밀번호) |
| 11 | Random Password | - | DB 비밀번호 자동 생성 |
| 12 | Redis Instance | `realtor-staging-redis` | Redis 7.2, 1GB, BASIC 티어 |
| 13 | Storage Bucket | `realtor-staging-reports` | 보고서 PDF/차트 이미지 (자동 아카이브) |
| 14 | Storage Bucket | `realtor-staging-static` | 프론트엔드 정적 자산 |

---

## 3. 남은 Phase 0 항목

| 항목 | 우선순위 | 비용 영향 | 비고 |
|------|---------|---------|------|
| **`terraform apply`** | 높음 | **~$200-300/월 시작** | staging 인프라 실제 생성 |
| 예산 알림 설정 ($500) | 높음 | 없음 | 웹 콘솔에서 수동 설정 |
| 도메인 구매 | 중간 | ~₩15,000/년 | 가비아 또는 Cloudflare |
| Cloud DNS Zone 생성 | 중간 | 없음 (프리 티어) | 도메인 구매 후 |
| GitHub 레포 3개 생성 | 중간 | 없음 | backend, worker, frontend |
| GitHub Actions Secrets 등록 | 낮음 | 없음 | CI/CD 구성 시 |
| CI/CD 파이프라인 작성 | 낮음 | 없음 | Phase 1 진입 시 |

---

## 4. 다음 단계 선택지

### 옵션 A: `terraform apply` — 인프라 먼저 생성

```bash
# 컨테이너에서 실행
cd /workspace/codes/realtor-ai-infra/terraform/environments/staging
terraform apply
```

- GKE, DB, Redis, Storage가 실제로 만들어짐
- 이후 K8s 매니페스트 배포 + 서비스 연동 테스트 가능
- **비용:** 즉시 과금 시작 (~$200-300/월)
- **추천 시점:** Phase 1-B (파이프라인 통합) 시작 시

### 옵션 B: Phase 1-A — Go 백엔드 코드 작성 먼저

- 인프라 없이 로컬에서 Go API 서버 개발 가능
- `realtor-ai-backend` 레포 생성 → 인증/결제/보고서 API 스켈레톤
- 로컬 Docker Compose로 PostgreSQL + Redis 실행하면서 개발
- **비용:** $0 (인프라 비용 절약)
- **추천:** 비용 최적화 우선 시

### 옵션 C: 나머지 GitHub 레포 3개 생성

- `realtor-ai-backend`, `realtor-ai-worker`, `realtor-ai-frontend` 생성
- 각 레포 초기 구조 셋업 (.gitignore, Dockerfile 스켈레톤, CI 워크플로우)
- **비용:** $0
- **추천:** 전체 프로젝트 구조를 먼저 잡고 싶을 때

### 권장 순서

```
옵션 C (레포 생성, 30분)
  → 옵션 B (Go 백엔드 개발, 2-3주)
  → 옵션 A (terraform apply, Phase 1-B 시작 시)
```

비용 발생을 최대한 늦추면서 개발 진행 가능.

---

## 5. 파일 구조 현황

```
codes/
├── gcp_build/                          # GCP Dev/Ops 컨테이너
│   ├── Dockerfile
│   ├── docker-compose.yaml
│   ├── entrypoint.sh
│   └── scripts/
│       └── init-gcp.sh                 # GCP 초기 설정 (1회 실행)
│
└── realtor-ai-infra/                   # Terraform + K8s 인프라 (GitHub 연결됨)
    ├── .gitignore
    └── terraform/
        ├── versions.tf
        ├── variables.tf
        ├── main.tf
        ├── outputs.tf
        ├── modules/
        │   ├── networking/             # VPC + 서브넷 + NAT
        │   ├── gke/                    # GKE Autopilot
        │   ├── cloudsql/               # PostgreSQL 15
        │   ├── memorystore/            # Redis 7.2
        │   └── storage/               # Cloud Storage
        └── environments/
            ├── staging/                # staging 환경
            └── production/             # production 환경
```
