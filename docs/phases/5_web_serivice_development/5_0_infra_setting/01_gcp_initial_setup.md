# GCP 초기 설정 가이드

> AWS 경험자를 위한 GCP 대응 가이드 포함  
> Docker 컨테이너 기반 GCP 개발 환경  
> 최종 업데이트: 2026-04-06

---

## 0. AWS ↔ GCP 핵심 용어 대응표

| AWS | GCP | 설명 |
|-----|-----|------|
| Account | **Project** | 리소스 격리 단위. GCP는 하나의 계정(Organization) 아래 여러 Project 생성 |
| Region / AZ | **Region / Zone** | 동일 개념. 서울 = `asia-northeast3` |
| IAM User | **Google Account / Service Account** | 사람 = Google 계정, 서비스 = Service Account |
| IAM Role | **IAM Role** | 동일하나, GCP는 더 세분화 (predefined roles) |
| IAM Policy (JSON) | **IAM Binding** | 역할을 주체(member)에 바인딩 |
| VPC | **VPC Network** | 거의 동일. GCP VPC는 글로벌 (리전별 서브넷) |
| Security Group | **Firewall Rules** | VPC 단위 방화벽 규칙 |
| EC2 | **Compute Engine** | 가상 머신 |
| EKS | **GKE (Google Kubernetes Engine)** | 매니지드 K8s |
| RDS | **Cloud SQL** | 매니지드 DB |
| ElastiCache | **Memorystore** | 매니지드 Redis |
| S3 | **Cloud Storage** | 오브젝트 스토리지 |
| ECR | **Artifact Registry** | 컨테이너 이미지 레지스트리 |
| ALB | **Cloud Load Balancing** | L7 로드밸런서 |
| CloudFront | **Cloud CDN** | CDN |
| Secrets Manager | **Secret Manager** | 시크릿 관리 |
| CloudWatch | **Cloud Monitoring + Cloud Logging** | 모니터링 + 로깅 |
| CloudFormation | **Deployment Manager** (비추) / **Terraform** (추천) | IaC |
| AWS CLI | **gcloud CLI** | 명령줄 도구 |
| aws configure | **gcloud auth login + gcloud config set project** | 인증 설정 |

---

## 1. GCP 계정 및 프로젝트 생성 (웹 콘솔 — 1회성)

이 단계는 Docker 컨테이너가 아닌 **웹 브라우저에서 수행**합니다.

### 1.1 Google Cloud 계정 생성

1. https://cloud.google.com 접속 → "무료로 시작하기" 클릭
2. Google 계정으로 로그인
3. 결제 정보 입력 (신용카드 필수 — $300 무료 크레딧 제공, 90일간)

### 1.2 프로젝트 생성

1. https://console.cloud.google.com → 상단 프로젝트 드롭다운 → "새 프로젝트"
2. 프로젝트 이름: `Realtor AI Advisor`
3. 프로젝트 ID: `realtor-ai-prod` (전세계 유일해야 함)
4. "만들기" 클릭

### 1.3 결제 계정 연결

콘솔: 결제 → 내 프로젝트 → `realtor-ai-prod` → 결제 계정 연결

---

## 2. 호스트에서 gcloud 인증 (1회성)

Docker 컨테이너는 호스트의 gcloud 인증을 그대로 사용합니다.
호스트에서 아래 인증을 먼저 완료하세요.

### 2.1 gcloud CLI 설치 (호스트에 미설치 시)

```bash
# Ubuntu/Debian
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] \
  https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list

sudo apt-get update && sudo apt-get install -y google-cloud-cli
```

### 2.2 인증 및 프로젝트 설정

```bash
# 브라우저 기반 로그인 (1회)
gcloud auth login

# 프로젝트 설정
gcloud config set project realtor-ai-prod

# 서울 리전 기본값
gcloud config set compute/region asia-northeast3
gcloud config set compute/zone asia-northeast3-a

# Application Default Credentials (Terraform 등에서 사용)
gcloud auth application-default login

# 설정 확인
gcloud config list
```

> **확인 포인트:** `~/.config/gcloud/` 디렉토리에 `credentials.db`, 
> `application_default_credentials.json` 파일이 생성되면 완료.

---

## 3. GCP Dev/Ops Docker 컨테이너

### 3.1 개요

GCP 인프라 작업에 필요한 모든 도구를 Docker 컨테이너로 패키징.
호스트 환경을 오염시키지 않으면서 terraform, kubectl 등을 사용할 수 있습니다.

**컨테이너에 포함된 도구:**

| 도구 | 버전 | 용도 |
|------|------|------|
| gcloud CLI | latest | GCP 리소스 관리 |
| gke-gcloud-auth-plugin | latest | GKE 클러스터 인증 |
| terraform | 1.11.4 | IaC (인프라 코드) |
| kubectl | latest stable | K8s 클러스터 관리 |
| gh (GitHub CLI) | latest | GitHub 레포/PR 관리 |
| Go | 1.24.2 | 백엔드 개발 |
| Node.js | 20.x | 프론트엔드 개발 |
| Python 3 | 3.12 (Ubuntu) | 워커 개발 |

**볼륨 마운트 구조:**

| 호스트 경로 | 컨테이너 경로 | 용도 |
|------------|-------------|------|
| `/home/gon/ws/rag` | `/workspace` | 프로젝트 소스코드 |
| `~/.config/gcloud` | `/root/.config/gcloud` | GCP 인증 (핵심) |
| `~/.ssh` | `/root/.ssh` (읽기 전용) | Git SSH 키 |
| Named: `gcp-kube-config` | `/root/.kube` | kubectl 설정 |
| Named: `gcp-terraform-cache` | `/root/.terraform.d` | Terraform 플러그인 캐시 |
| Named: `gcp-go-cache` | `/root/go` | Go 모듈 캐시 |
| Named: `gcp-npm-cache` | `/root/.npm` | npm 캐시 |

### 3.2 이미지 빌드

```bash
cd /home/gon/ws/rag/codes/gcp_build

# 빌드 (ARM64 네이티브, 약 5-10분 소요)
docker compose build
```

> **베이스 이미지:** `ubuntu:24.04` (ARM64 네이티브)  
> `google/cloud-sdk` 공식 이미지는 amd64 전용이므로 사용하지 않습니다.

### 3.3 컨테이너 실행

```bash
# 인터랙티브 셸 진입 (가장 일반적)
docker compose run --rm gcp-dev

# 또는 백그라운드로 띄우고 exec
docker compose up -d
docker exec -it rag-gcp-dev bash
```

컨테이너 진입 시 자동으로 표시되는 진단 배너:

```
=== GCP Dev/Ops Container ===
gcloud   : Google Cloud SDK 563.0.0
terraform: Terraform v1.11.4
kubectl  : Client Version: v1.32.x
gh       : gh version 2.x.x
go       : go version go1.24.2 linux/arm64
node     : v20.x.x
python3  : Python 3.12.3

GCP account : y2gon3@gmail.com
GCP project : realtor-ai-prod
GCP region  : asia-northeast3
==============================
```

### 3.4 컨테이너 내부 — 초기 설정 (1회만)

아래 작업들은 **GCP 서버 측에 영구 저장**되므로, 컨테이너를 재시작해도 다시 할 필요 없습니다.

| 작업 | 실행 빈도 | 이유 |
|------|----------|------|
| API 활성화 | **1회** | GCP 프로젝트에 영구 적용 |
| IAM 서비스 계정 생성 | **1회** | 삭제하지 않는 한 유지 |
| 예산 알림 | **1회** | 설정 후 계속 동작 |
| Artifact Registry | **1회** | 레지스트리 영구 유지 |
| Terraform 상태 버킷 | **1회** | 버킷 영구 유지 |
| GitHub CLI 인증 | **1회** | 토큰 만료 시만 재인증 |

#### 3.4.1 초기 설정 스크립트 실행 (1회)

모든 초기 설정을 하나의 스크립트로 실행합니다.
이미 완료된 항목은 자동으로 건너뛰므로(멱등성), 실수로 다시 실행해도 문제없습니다.

```bash
# 컨테이너 진입
docker compose run --rm gcp-dev

# 초기 설정 스크립트 실행 (1회)
bash /workspace/codes/gcp_build/scripts/init-gcp.sh
```

스크립트가 수행하는 작업:
1. GCP 인증 상태 확인
2. API 13개 활성화
3. IAM 서비스 계정 3개 생성 + 역할 바인딩
4. Terraform 키 파일 생성
5. Artifact Registry 생성
6. Terraform 상태 버킷 생성
7. `.gitignore`에 `.secrets/` 추가 확인

각 항목의 상세 설명은 아래 **섹션 3.5 "초기 설정 항목 상세 설명"** 을 참조하세요.

#### 3.4.2 수동 후속 작업 (1회)

스크립트 완료 후 수동으로 진행:

```bash
# 1. 예산 알림 — 웹 콘솔에서 설정 (CLI보다 직관적)
#    https://console.cloud.google.com/billing → 예산 및 알림
#    금액: $500, 알림: 50%/75%/100%

# 2. GitHub CLI 인증
gh auth login
# → GitHub.com → HTTPS → 브라우저 인증 또는 토큰 입력

# 3. GCP 인증이 안 되어 있는 경우 (보통은 호스트에서 자동 전달됨)
gcloud auth login --no-launch-browser
# → URL 출력 → 호스트 브라우저에 붙여넣기 → 코드 복사 → 입력
```

#### 3.4.3 이후 컨테이너 재진입 시

초기 설정 완료 후에는 그냥 진입만 하면 됩니다:

```bash
docker compose run --rm gcp-dev
# → 배너에서 인증/도구 상태 자동 확인
# → 바로 terraform, kubectl, gcloud 등 사용 가능
```

### 3.5 초기 설정 항목 상세 설명

#### (1) GCP API 활성화 — "GCP한테 어떤 서비스를 쓸 건지 미리 알려주는 것"

GCP는 AWS와 다르게, 서비스를 사용하기 전에 **명시적으로 "이 API를 쓰겠다"고 켜줘야** 합니다.
비유하면 스마트폰에서 앱을 설치하는 것과 비슷합니다 — 앱스토어에 앱이 있지만 설치하기 전에는 사용할 수 없는 것처럼.

활성화한 13개 API가 각각 무엇인지:

| API | 무엇을 하는 건지 | 우리 프로젝트에서 왜 필요한지 |
|-----|----------------|--------------------------|
| **container.googleapis.com** | GKE (Google Kubernetes Engine) — 쿠버네티스 클러스터를 만들고 관리하는 서비스. 쿠버네티스는 Docker 컨테이너 여러 개를 자동으로 배포/확장/관리해주는 오케스트레이션 도구. | Go API 서버, Python Worker, Qdrant 등 모든 서비스를 GKE 클러스터에 배포 |
| **sqladmin.googleapis.com** | Cloud SQL — GCP가 관리해주는 데이터베이스(PostgreSQL, MySQL). 설치/백업/장애 복구를 GCP가 알아서 해줌. | 사용자 정보, 보고서 기록, 결제 내역 등을 저장하는 PostgreSQL DB |
| **redis.googleapis.com** | Memorystore — GCP가 관리해주는 Redis. Redis는 데이터를 메모리(RAM)에 저장하는 초고속 Key-Value 저장소. | API 응답 캐싱 (같은 요청을 반복하지 않기 위해), 로그인 세션 관리, 보고서 생성 작업 큐 |
| **storage.googleapis.com** | Cloud Storage — 파일 저장소. AWS의 S3와 동일. 이미지, PDF, 영상 등 파일을 저장하고 URL로 접근. | 생성된 PDF 보고서, 차트 이미지 저장. 사용자에게 다운로드 링크 제공 |
| **compute.googleapis.com** | Compute Engine — 가상 머신(VM). AWS의 EC2. GKE도 내부적으로 VM 위에서 돌아가므로 필요. | GKE 클러스터의 노드(실제 서버 머신)를 생성하기 위해 |
| **artifactregistry.googleapis.com** | Artifact Registry — Docker 이미지 저장소. AWS의 ECR. 빌드한 Docker 이미지를 업로드해두면 GKE가 여기서 이미지를 가져다 컨테이너를 실행. | Go API, Python Worker, Next.js 등의 Docker 이미지를 저장 |
| **secretmanager.googleapis.com** | Secret Manager — 비밀번호, API 키 같은 민감 정보를 안전하게 저장하고 접근을 통제. 코드에 하드코딩하지 않고 런타임에 가져다 쓰는 방식. | Anthropic API 키, Toss Payments 시크릿 키, DB 비밀번호 등 관리 |
| **servicenetworking.googleapis.com** | Service Networking — GCP 내부 서비스들끼리 VPC(가상 사설 네트워크) 안에서 Private IP로 통신하게 해주는 서비스. | Cloud SQL DB에 인터넷 노출 없이 GKE에서만 접근 가능하게 (보안) |
| **cloudresourcemanager.googleapis.com** | Resource Manager — GCP 프로젝트, 폴더, 조직을 관리하는 API. | Terraform이 프로젝트 설정을 읽고 변경하기 위해 |
| **iam.googleapis.com** | IAM (Identity and Access Management) — "누가 무엇을 할 수 있는지" 권한을 관리. 사용자나 서비스 계정에 특정 역할(role)을 부여. | 서비스 계정 생성, 역할 바인딩 (Go API는 DB만 접근, Worker는 Storage도 접근 등) |
| **monitoring.googleapis.com** | Cloud Monitoring — 서버 CPU, 메모리, 요청 수, 에러율 등을 실시간 그래프로 보여주고, 이상 시 알림을 보내는 서비스. | 서비스 장애 감지, API 응답 시간 모니터링, 큐 깊이 감시 |
| **logging.googleapis.com** | Cloud Logging — 모든 서비스의 로그(출력)를 중앙에서 수집/검색. `console.log`나 `print`로 출력한 내용을 브라우저에서 검색 가능. | 에러 추적, 디버깅, 보안 감사 (누가 언제 무엇을 했는지) |
| **certificatemanager.googleapis.com** | Certificate Manager — HTTPS를 위한 SSL/TLS 인증서를 자동 발급/갱신. 인증서가 없으면 브라우저에 "안전하지 않은 사이트"라고 표시됨. | `api.example.kr`, `app.example.kr` 등 도메인에 HTTPS 적용 |
| **dns.googleapis.com** | Cloud DNS — 도메인 네임 시스템 관리. "app.example.kr"이라는 주소를 실제 서버 IP로 변환해주는 서비스. | 도메인을 GKE 로드밸런서 IP에 연결 |

#### (2) IAM 서비스 계정 — "사람이 아닌 프로그램에게 주는 GCP 출입증"

**서비스 계정(Service Account)이란?**

사람이 `gcloud auth login`으로 로그인하듯, **프로그램(서버, CI/CD)도 GCP에 로그인이 필요**합니다.
서비스 계정은 프로그램 전용 계정입니다. 이메일처럼 생긴 ID (`terraform-admin@realtor-ai-prod.iam.gserviceaccount.com`)를 가지며, JSON 키 파일이 비밀번호 역할을 합니다.

**왜 별도 계정을 만드나?** — **최소 권한 원칙(Principle of Least Privilege)**

내 개인 GCP 계정(`y2gon3@gmail.com`)은 프로젝트의 "Owner"라서 모든 것을 할 수 있습니다.
하지만 Go API 서버에 내 계정을 그대로 쓰면, 서버가 해킹당했을 때 공격자가 프로젝트 전체를 삭제할 수도 있습니다.
그래서 **각 프로그램에 필요한 최소한의 권한만** 가진 전용 계정을 만듭니다.

생성한 3개 서비스 계정:

| 서비스 계정 | 누가 사용하나 | 할 수 있는 것 | 할 수 없는 것 |
|------------|-------------|-------------|-------------|
| **terraform-admin** | Terraform (인프라 코드 도구) | GKE 클러스터 생성/삭제, DB 생성, 네트워크 설정 등 인프라 전체 관리 | — (인프라 관리자이므로 넓은 권한) |
| **go-api-sa** | Go API 서버 (프로덕션) | DB 접속, Secret Manager 읽기, Storage 파일 업로드/다운로드 | GKE 클러스터 삭제, 서비스 계정 생성, 네트워크 변경 등은 불가 |
| **python-worker-sa** | Python Worker (보고서 생성) | DB 접속, Secret Manager 읽기, Storage 파일 업로드/다운로드 | 위와 동일하게 인프라 변경 불가 |

**역할 바인딩(Role Binding)이란?**

"이 계정에 이 역할을 부여한다"는 설정. 예:
- `go-api-sa`에 `roles/cloudsql.client` 바인딩 → "Go API는 Cloud SQL DB에 접속할 수 있다"
- `go-api-sa`에 `roles/storage.objectAdmin` 바인딩 → "Go API는 Cloud Storage에 파일을 올리고 읽을 수 있다"

#### (3) Terraform 키 파일 — "Terraform이 GCP에 로그인하기 위한 비밀번호 파일"

Terraform은 코드(.tf 파일)로 인프라를 생성하는 도구입니다.
`terraform apply`를 실행하면 GCP에 "GKE 클러스터를 만들어줘"라고 API를 호출하는데,
이때 **"나는 terraform-admin이야"라고 증명**하기 위해 JSON 키 파일이 필요합니다.

```
terraform-key.json = terraform-admin 서비스 계정의 비밀번호 (JSON 형식)
```

이 파일은 `.secrets/` 폴더에 저장되고, `.gitignore`에 등록되어 Git에 절대 커밋되지 않습니다.
이 파일이 유출되면 누구나 우리 GCP 인프라를 조작할 수 있으므로 매우 중요합니다.

**동작 흐름:**
```
개발자 → terraform apply 실행
         → Terraform이 terraform-key.json을 읽음
         → "나는 terraform-admin이야"라고 GCP에 인증
         → GCP가 역할 확인 → 허용된 작업만 수행
```

#### (4) Artifact Registry — "Docker 이미지 창고"

**Docker 이미지란?**

Docker 이미지는 "프로그램 + 실행 환경을 하나로 묶은 패키지"입니다.
예를 들어 Go API 서버를 이미지로 만들면, Go 런타임 + 컴파일된 바이너리 + 설정 파일이 하나의 파일로 묶입니다.

**Artifact Registry란?**

이 Docker 이미지를 **업로드해두는 저장소**입니다.
이미지를 여기에 올려두면(push), GKE가 여기서 이미지를 가져다(pull) 컨테이너를 실행합니다.

```
개발자 PC에서 이미지 빌드
    ↓ docker push
Artifact Registry (asia-northeast3, 서울)
    ↓ docker pull (자동)
GKE 클러스터에서 컨테이너 실행
```

**비유:** GitHub이 소스코드 저장소라면, Artifact Registry는 실행 파일 저장소.

우리 프로젝트에서 저장하는 이미지들:
- `realtor-ai/go-api:v1.0.0` — Go API 서버
- `realtor-ai/python-worker:v1.0.0` — Python 보고서 생성 워커
- `realtor-ai/nextjs:v1.0.0` — Next.js 웹 프론트엔드

#### (5) Terraform 상태 버킷 — "인프라 현재 상태를 기록하는 공유 노트"

**Terraform 상태(State)란?**

Terraform은 "코드에 적힌 인프라"와 "실제 GCP에 존재하는 인프라"를 비교해서 차이점만 적용합니다.
이를 위해 **"지금 GCP에 뭐가 있는지"를 기록한 상태 파일(terraform.tfstate)**이 필요합니다.

```
예시: terraform.tfstate 내용 (간략화)
{
  "gke_cluster": "realtor-cluster (존재함, 노드 3개)",
  "cloud_sql": "realtor-db (존재함, PostgreSQL 15, 20GB)",
  "redis": "realtor-cache (존재함, 1GB)"
}
```

Terraform이 `terraform apply`를 실행할 때:
1. 코드(.tf)를 읽음: "GKE 클러스터 노드 5개 원함"
2. 상태 파일을 읽음: "현재 노드 3개"
3. 차이 계산: "노드 2개 추가 필요"
4. GCP에 노드 2개 추가 요청
5. 상태 파일 업데이트: "현재 노드 5개"

**왜 Cloud Storage 버킷에 저장하나?**

상태 파일을 로컬 PC에만 두면:
- 다른 팀원이 `terraform apply`하면 서로 상태가 다르므로 충돌 발생
- PC가 고장나면 상태 파일 분실 → Terraform이 기존 인프라를 모르게 됨

그래서 GCS(Cloud Storage) 버킷에 원격 저장하고, 버전 관리를 켜서 실수로 덮어써도 복구 가능하게 합니다.

```
[개발자 A] → terraform apply → tfstate 읽기/쓰기 ← GCS 버킷 (gs://realtor-ai-terraform-state)
[개발자 B] → terraform apply → 같은 tfstate 사용 ↗
[CI/CD]    → terraform apply → 같은 tfstate 사용 ↗
```

**비유:** Google Docs처럼 여러 사람이 같은 문서를 동시에 편집할 수 있게 하는 것. 
로컬 파일은 Word 문서를 USB로 주고받는 것과 같아서 버전 충돌이 일어남.

---

### 3.6 컨테이너 종료 및 재진입

```bash
# 종료
exit

# 재진입 — 모든 캐시와 인증이 유지됨
docker compose run --rm gcp-dev

# Named 볼륨 정리 (필요시)
docker compose down -v
```

### 3.7 원샷 명령 실행

셸 진입 없이 단일 명령 실행:

```bash
cd /home/gon/ws/rag/codes/gcp_build

docker compose run --rm gcp-dev terraform plan
docker compose run --rm gcp-dev kubectl get pods
docker compose run --rm gcp-dev gcloud compute instances list
docker compose run --rm gcp-dev gh repo list
```

---

## 4. 도메인 및 DNS 설정

### 4.1 도메인 구매

- 가비아 (https://www.gabia.com) — 한국 도메인(.kr, .co.kr)
- Cloudflare (https://www.cloudflare.com) — 글로벌 도메인(.com, .io)

### 4.2 Cloud DNS Zone 생성 (컨테이너 내부에서)

```bash
gcloud dns managed-zones create realtor-ai-zone \
  --dns-name="example.kr." \
  --description="부동산 AI 어드바이저 DNS" \
  --visibility=public

# NS 레코드 확인 → 도메인 등록 업체에 등록
gcloud dns managed-zones describe realtor-ai-zone --format="value(nameServers)"
```

### 4.3 서브도메인 계획

| 서브도메인 | 용도 |
|-----------|------|
| `app.example.kr` | 웹 프론트엔드 |
| `api.example.kr` | Go API 서버 |
| `example.kr` | 랜딩 페이지 |

---

## 5. GitHub 레포지토리 구성

### 5.1 추천: 하이브리드 (4개 레포)

```
GitHub Organization 또는 개인 계정
│
├── realtor-ai-backend          # Go API 서버
├── realtor-ai-worker           # Python 보고서 생성 워커
├── realtor-ai-frontend         # Next.js 웹 프론트엔드
└── realtor-ai-infra            # Terraform + K8s 매니페스트 + CI/CD
```

### 5.2 레포 생성 (컨테이너 내부에서)

```bash
gh repo create realtor-ai-backend --private --description "Go API 서버"
gh repo create realtor-ai-worker --private --description "Python 보고서 생성 워커"
gh repo create realtor-ai-frontend --private --description "Next.js 웹 프론트엔드"
gh repo create realtor-ai-infra --private --description "Terraform + K8s 인프라 코드"
```

### 5.3 각 레포 구조

#### realtor-ai-backend (Go API)

```
├── cmd/server/main.go
├── internal/
│   ├── auth/       # JWT + OAuth2 (카카오/네이버/Google)
│   ├── user/       # 사용자 CRUD
│   ├── payment/    # Toss Payments
│   ├── report/     # 보고서 관리 + 잡 큐 발행
│   ├── address/    # 주소 정규화
│   ├── cache/      # Redis
│   ├── middleware/  # 인증, Rate Limit, CORS
│   └── sse/        # 진행률 스트리밍
├── migrations/     # SQL 마이그레이션
├── Dockerfile
├── go.mod
└── .golangci.yml
```

#### realtor-ai-worker (Python)

```
├── worker/         # Redis Stream 컨슈머
├── api/            # 기존 codes/api/ 이관
├── report/         # 기존 codes/report/ 이관
├── generation/     # LLM 클라이언트
├── rules/          # 세금/대출 룰엔진
├── query/          # RAG 검색
├── Dockerfile
└── requirements.txt
```

#### realtor-ai-frontend (Next.js)

```
├── src/app/        # App Router 페이지
├── src/components/ # React 컴포넌트
├── src/hooks/      # useAuth, useSSE 등
├── src/lib/        # API 클라이언트
├── Dockerfile
├── next.config.ts
└── package.json
```

#### realtor-ai-infra (Terraform + K8s)

```
├── terraform/
│   ├── environments/{staging,production}/
│   └── modules/{networking,gke,cloudsql,memorystore,storage,iam,loadbalancer,secrets}/
├── k8s/
│   ├── base/{go-api,python-worker,qdrant,embedding-server,nextjs}/
│   └── overlays/{staging,production}/
├── scripts/        # 유틸리티 스크립트
└── .github/workflows/
```

### 5.4 GitHub Actions Secrets

각 레포의 Settings → Secrets and variables → Actions에 등록:

| Secret | 값 | 레포 |
|--------|-----|------|
| `GCP_PROJECT_ID` | `realtor-ai-prod` | 전체 |
| `GCP_REGION` | `asia-northeast3` | 전체 |
| `GCP_SA_KEY` | Terraform SA 키 JSON (base64) | `infra` |
| `GKE_SA_KEY` | 배포용 SA 키 JSON (base64) | `backend`, `worker`, `frontend` |
| `ARTIFACT_REGISTRY` | `asia-northeast3-docker.pkg.dev/realtor-ai-prod/realtor-ai` | `backend`, `worker`, `frontend` |

### 5.5 .gitignore (공통)

```gitignore
# 시크릿 (절대 커밋 금지)
*.key
*.pem
terraform-key.json
.env
.env.*
!.env.example
.secrets/

# Terraform
*.tfstate
*.tfstate.*
.terraform/
.terraform.lock.hcl

# IDE / OS
.vscode/
.idea/
*.swp
.DS_Store
```

---

## 6. Phase 0 전체 체크리스트

### 웹 콘솔 작업 (1회성)

- [ ] GCP 계정 생성 + $300 무료 크레딧
- [ ] 프로젝트 생성: `realtor-ai-prod`
- [ ] 결제 계정 연결

### 호스트 작업 (1회성)

- [ ] gcloud CLI 설치 (이미 완료)
- [ ] `gcloud auth login` (이미 완료: y2gon3@gmail.com)
- [ ] `gcloud config set project realtor-ai-prod` (이미 완료)
- [ ] `gcloud auth application-default login` (이미 완료)
- [ ] Docker 이미지 빌드: `cd codes/gcp_build && docker compose build`

### 컨테이너 내부 작업

- [ ] GCP API 13개 활성화 (섹션 3.4.2)
- [ ] Terraform용 IAM 서비스 계정 생성 (섹션 3.4.3)
- [ ] GKE 워크로드용 IAM 서비스 계정 생성 (섹션 3.4.3)
- [ ] 예산 알림 $500 설정 (섹션 3.4.4)
- [ ] Artifact Registry 생성 (섹션 3.4.5)
- [ ] Terraform 상태 버킷 생성 (섹션 3.4.6)
- [ ] GitHub CLI 인증 + 레포 4개 생성 (섹션 3.4.7, 5.2)
- [ ] GitHub Actions Secrets 등록 (섹션 5.4)

### 외부 서비스 (Phase 1 시작 전까지)

- [ ] 도메인 구매 (가비아 또는 Cloudflare)
- [ ] Toss Payments 가맹점 등록 (사업자등록증 필요)
- [ ] 카카오 개발자 앱 등록 (OAuth + REST API)
- [ ] 네이버 개발자 앱 등록 (OAuth)
- [ ] Google Cloud OAuth 클라이언트 생성
- [ ] data.go.kr 운영 계정 신청 (일일 한도 업그레이드)

---

## 7. 파일 위치

| 파일 | 경로 | 용도 |
|------|------|------|
| Dockerfile | `codes/gcp_build/Dockerfile` | 컨테이너 이미지 정의 |
| docker-compose.yaml | `codes/gcp_build/docker-compose.yaml` | 볼륨 마운트 + 환경 설정 |
| entrypoint.sh | `codes/gcp_build/entrypoint.sh` | 진입 시 도구/인증 확인 |
| init-gcp.sh | `codes/gcp_build/scripts/init-gcp.sh` | GCP 초기 설정 (1회 실행) |
