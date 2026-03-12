# Qdrant 벡터 데이터베이스 컨테이너 실행 가이드 (DGX Spark)

> 작성일: 2026-03-12
> Qdrant 버전: v1.17.0 (2025-02-20 릴리스, 최신 안정 버전)
> 목적: DGX Spark(GB10)에서 Qdrant를 Docker 컨테이너로 안정적으로 실행

---

## 1. Qdrant란?

Qdrant는 Rust로 작성된 오픈소스 벡터 데이터베이스로, 벡터 유사도 검색과 함께 페이로드 필터링, 하이브리드 검색(Dense + Sparse), gRPC/REST API를 지원한다.

### 이 프로젝트에서의 역할

```
KURE-v1 (임베딩 모델)    →    Qdrant (벡터 저장/검색)    →    Claude API (답변 생성)
  v2 문서 → 1024차원 벡터       Dense + BM25 하이브리드         출처 인용 RAG 답변
```

### 핵심 사양

| 항목 | 값 |
|------|-----|
| 라이선스 | Apache 2.0 |
| 최신 버전 | v1.17.0 (2025-02-20) |
| 포트 | 6333 (REST), 6334 (gRPC), 6335 (분산 클러스터) |
| 스토리지 | POSIX 호환 블록 스토리지 필수 (NFS/S3 불가) |
| 아키텍처 | linux/amd64, linux/arm64 공식 지원 |

---

## 2. DGX Spark 호환성 조사

### 2-1. ARM64 공식 지원 여부

Qdrant Docker 이미지(`qdrant/qdrant`)는 **멀티플랫폼 빌드**를 제공하며, `linux/arm64` 를 공식 지원한다. Docker가 호스트 아키텍처를 자동 감지하여 올바른 이미지를 pull한다.

```
DGX Spark 아키텍처:  aarch64 (linux/arm64)  ✅ 공식 지원
```

### 2-2. jemalloc 페이지 사이즈 이슈

Qdrant는 메모리 할당자로 jemalloc을 사용한다. ARM64 시스템에서 **시스템 페이지 사이즈가 64KB(65536)**인 경우 다음 에러가 발생할 수 있다:

```
<jemalloc>: Unsupported system page size
memory allocation of 5 bytes failed
```

**DGX Spark 확인 결과:**

```bash
$ getconf PAGESIZE
4096
```

DGX Spark의 페이지 사이즈는 **4KB (4096)** → jemalloc 기본 빌드와 호환되므로 **이 이슈는 해당 없음**.

> **참고**: DGX Spark에서 64KB 커널로 전환하면 NVIDIA 드라이버 모듈 로딩 실패 등 심각한 호환성 문제가 발생한다. 현재 기본 커널(4KB 페이지)을 유지하는 것이 권장된다.

### 2-3. 관련 GitHub 이슈 정리

| 이슈 | 영향 | DGX Spark 해당 여부 |
|------|------|---------------------|
| [#4298](https://github.com/qdrant/qdrant/issues/4298) — jemalloc 페이지 사이즈 불일치 | 64KB 페이지 시스템에서 실행 불가 | ❌ (4KB 페이지) |
| [#5952](https://github.com/qdrant/qdrant/issues/5952) — ARM64 jemalloc 문제 | v1.11.4-arm64 등에서 발생 | ❌ (4KB 페이지) |
| [#2474](https://github.com/qdrant/qdrant/issues/2474) — 초기 ARM64 지원 이슈 | v1.6 이전 버전에서 발생 | ❌ (최신 버전 사용) |

### 2-4. 성능 참고

Qdrant 공식 벤치마크에 따르면 ARM64는 x86_64 대비:
- 평균 **10% 느림**, 중앙값 기준 **20% 느림**
- 하지만 AWS 기준 **20% 저렴**하여 비용 대비 효율적

DGX Spark는 128GB 통합 메모리 + NVLink 구조이므로, 10만 벡터 규모(Phase 1 목표)에서는 충분한 성능이 예상된다.

---

## 3. Docker 이미지 선택

### 3-1. 사용할 이미지

```
qdrant/qdrant:v1.17.0
```

| 항목 | 값 |
|------|-----|
| Docker Hub | [qdrant/qdrant](https://hub.docker.com/r/qdrant/qdrant) |
| GHCR | ghcr.io/qdrant/qdrant |
| 이미지 크기 | ~100MB (Rust 네이티브 바이너리, 경량) |
| 플랫폼 | linux/amd64, linux/arm64 (멀티플랫폼 manifest) |

> **NGC 컨테이너가 아닌 이유**: Qdrant는 Rust 네이티브 바이너리로, PyTorch/CUDA에 의존하지 않는다. NGC 이미지가 필요 없으며, 공식 Docker Hub 이미지를 그대로 사용하면 된다.

### 3-2. 태그 선택 가이드

| 태그 | 용도 | 비고 |
|------|------|------|
| `v1.17.0` | **프로덕션 권장** | 특정 버전 고정으로 재현성 확보 |
| `latest` | 빠른 테스트 | 자동 업데이트 → 호환성 깨질 수 있음 |
| `v1.17.0-unprivileged` | 보안 강화 환경 | root 권한 없이 실행 |

---

## 4. 실행 방법

### 4-1. 방식 A — 직접 Docker 실행 (빠른 테스트)

```bash
# Qdrant 컨테이너 실행
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant:v1.17.0

# 헬스체크
curl http://localhost:6333/healthz
# 정상 응답: (빈 문자열 또는 200 OK)

# 버전 확인
curl http://localhost:6333 | python3 -m json.tool
# 예: {"title":"qdrant","version":"1.17.0", ...}
```

**볼륨 마운트 설명:**

| 호스트 경로 | 컨테이너 경로 | 용도 |
|-------------|---------------|------|
| `/home/gon/ws/rag/qdrant_storage` | `/qdrant/storage` | 벡터 데이터 영구 저장 |

> `:z` 플래그: SELinux 환경에서 볼륨 접근 허용 (DGX Spark Ubuntu에서는 선택적이지만 안전을 위해 유지)

### 4-2. 방식 B — Docker Compose (장기 운영 권장)

```yaml
# docker-compose.qdrant.yml
services:
  qdrant:
    image: qdrant/qdrant:v1.17.0
    container_name: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"   # REST API
      - "6334:6334"   # gRPC API
    volumes:
      - /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z
    configs:
      - source: qdrant_config
        target: /qdrant/config/production.yaml
    environment:
      - QDRANT__LOG_LEVEL=INFO

configs:
  qdrant_config:
    content: |
      log_level: INFO
      storage:
        # 온디스크 페이로드 저장 (메모리 절약)
        on_disk_payload: true
      service:
        # gRPC 활성화
        grpc_port: 6334
        enable_tls: false
```

```bash
# 실행
docker compose -f docker-compose.qdrant.yml up -d

# 로그 확인
docker compose -f docker-compose.qdrant.yml logs -f qdrant

# 중지
docker compose -f docker-compose.qdrant.yml down
```

### 4-3. 방식 C — 커스텀 설정 파일 사용

별도 설정 파일로 세밀한 제어가 필요한 경우:

```yaml
# config/qdrant_config.yaml
log_level: INFO

storage:
  # 벡터 데이터 저장 경로 (컨테이너 내부)
  storage_path: /qdrant/storage

  # 온디스크 페이로드 (대량 메타데이터 시 메모리 절약)
  on_disk_payload: true

  # 성능 튜닝
  performance:
    # 최적화 스레드 수 (0 = 자동)
    max_optimization_threads: 0

service:
  # REST API
  host: "0.0.0.0"
  http_port: 6333

  # gRPC API
  grpc_port: 6334

  # API 키 인증 (프로덕션 시 활성화)
  # api_key: "your-secret-api-key"
```

```bash
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z \
  -v /home/gon/ws/rag/config/qdrant_config.yaml:/qdrant/config/production.yaml \
  qdrant/qdrant:v1.17.0
```

---

## 5. 검증 스크립트

Qdrant가 정상 동작하는지 확인하는 Python 스크립트:

```python
# test_qdrant.py
"""
Qdrant 연결 및 기본 동작 검증 스크립트.
실행 전 Qdrant 컨테이너가 실행 중이어야 한다.

사용법:
    pip install qdrant-client
    python test_qdrant.py
"""
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams,
    PointStruct, SparseVectorParams, Modifier,
)

QDRANT_URL = "http://localhost:6333"
TEST_COLLECTION = "_test_verification"
VECTOR_DIM = 1024  # KURE-v1 임베딩 차원

def main():
    # 1. 연결 확인
    client = QdrantClient(url=QDRANT_URL)
    info = client.get_collections()
    print(f"✅ Qdrant 연결 성공")
    print(f"   기존 컬렉션: {[c.name for c in info.collections]}")

    # 2. 테스트 컬렉션 생성 (Dense + Sparse)
    if client.collection_exists(TEST_COLLECTION):
        client.delete_collection(TEST_COLLECTION)

    client.create_collection(
        collection_name=TEST_COLLECTION,
        vectors_config={
            "dense": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(modifier=Modifier.IDF),
        },
    )
    print(f"✅ 컬렉션 '{TEST_COLLECTION}' 생성 완료 (dense: {VECTOR_DIM}차원 + sparse BM25)")

    # 3. 테스트 포인트 삽입
    test_points = [
        PointStruct(
            id=1,
            vector={"dense": np.random.rand(VECTOR_DIM).tolist()},
            payload={
                "doc_id": "test_doc_001",
                "chunk_type": "atomic_fact",
                "channel": "test_channel",
                "topic_tags": ["세금/취득세"],
                "text": "다주택자 취득세 중과 기준 테스트 문서",
            },
        ),
        PointStruct(
            id=2,
            vector={"dense": np.random.rand(VECTOR_DIM).tolist()},
            payload={
                "doc_id": "test_doc_002",
                "chunk_type": "summary",
                "channel": "test_channel",
                "topic_tags": ["대출/DSR"],
                "text": "DSR 규제 관련 테스트 문서",
            },
        ),
    ]
    client.upsert(collection_name=TEST_COLLECTION, points=test_points)
    print(f"✅ 테스트 포인트 {len(test_points)}개 삽입 완료")

    # 4. 벡터 검색 테스트
    results = client.query_points(
        collection_name=TEST_COLLECTION,
        query=np.random.rand(VECTOR_DIM).tolist(),
        using="dense",
        limit=2,
    )
    print(f"✅ 벡터 검색 성공 — {len(results.points)}개 결과 반환")

    # 5. 페이로드 필터 검색 테스트
    from qdrant_client.models import Filter, FieldCondition, MatchAny
    filtered = client.query_points(
        collection_name=TEST_COLLECTION,
        query=np.random.rand(VECTOR_DIM).tolist(),
        using="dense",
        query_filter=Filter(
            must=[FieldCondition(key="topic_tags", match=MatchAny(any=["세금/취득세"]))]
        ),
        limit=5,
    )
    print(f"✅ 필터 검색 성공 — topic_tags='세금/취득세' → {len(filtered.points)}개 결과")

    # 6. 컬렉션 정보 확인
    col_info = client.get_collection(TEST_COLLECTION)
    print(f"✅ 컬렉션 상태: {col_info.status}, 포인트 수: {col_info.points_count}")

    # 7. 테스트 컬렉션 정리
    client.delete_collection(TEST_COLLECTION)
    print(f"✅ 테스트 컬렉션 삭제 완료")

    print("\n🎉 모든 검증 통과 — Qdrant가 정상 동작합니다!")

if __name__ == "__main__":
    main()
```

---

## 6. Phase 1 RAG MVP용 컬렉션 스키마

검증 통과 후, 실제 프로젝트용 컬렉션을 생성한다:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance,
    SparseVectorParams, Modifier,
    PayloadSchemaType,
)

client = QdrantClient("localhost", port=6333)

# 컬렉션 생성
client.create_collection(
    collection_name="realestate_v2",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF),
    },
)

# 페이로드 인덱스 생성 (필터 검색 성능 최적화)
for field, schema_type in [
    ("doc_id", PayloadSchemaType.KEYWORD),
    ("chunk_type", PayloadSchemaType.KEYWORD),
    ("channel", PayloadSchemaType.KEYWORD),
    ("upload_date", PayloadSchemaType.DATETIME),
    ("topic_tags", PayloadSchemaType.KEYWORD),
    ("region_tags", PayloadSchemaType.KEYWORD),
    ("asset_type", PayloadSchemaType.KEYWORD),
    ("reliability_score", PayloadSchemaType.INTEGER),
]:
    client.create_payload_index(
        collection_name="realestate_v2",
        field_name=field,
        field_schema=schema_type,
    )

print("✅ realestate_v2 컬렉션 + 페이로드 인덱스 생성 완료")
```

---

## 7. 운영 관리

### 상태 모니터링

```bash
# 헬스체크
curl -s http://localhost:6333/healthz

# 컬렉션 목록
curl -s http://localhost:6333/collections | python3 -m json.tool

# 특정 컬렉션 정보 (포인트 수, 상태 등)
curl -s http://localhost:6333/collections/realestate_v2 | python3 -m json.tool

# 텔레메트리 (메모리 사용량, 성능 통계)
curl -s http://localhost:6333/telemetry | python3 -m json.tool
```

### 백업 및 복구

```bash
# 스냅샷 생성
curl -X POST http://localhost:6333/collections/realestate_v2/snapshots

# 스냅샷 목록
curl http://localhost:6333/collections/realestate_v2/snapshots

# 스냅샷은 qdrant_storage/snapshots/ 디렉토리에 저장됨
ls /home/gon/ws/rag/qdrant_storage/snapshots/
```

### 컨테이너 관리

```bash
# 로그 확인
docker logs qdrant --tail 50

# 재시작 (데이터는 볼륨에 보존)
docker restart qdrant

# 완전 중지 및 제거 (데이터는 호스트 볼륨에 보존)
docker stop qdrant && docker rm qdrant

# 버전 업그레이드 (데이터 호환성 유지)
docker stop qdrant && docker rm qdrant
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant:v1.18.0  # 새 버전
```

---

## 8. 핵심 주의사항

### 스토리지 요구사항

Qdrant는 **POSIX 호환 블록 스토리지**가 필수이다. NFS, S3, 기타 네트워크 파일시스템은 지원하지 않는다. DGX Spark의 로컬 NVMe 스토리지를 사용하므로 문제 없음.

### 메모리 사용량 추정 (Phase 1)

```
예상 벡터 수:  ~100,000 (5,000 문서 × 20 청크)
벡터 차원:     1,024 (KURE-v1)
벡터 당 크기:  1,024 × 4 bytes (FP32) = 4KB
총 벡터 크기:  100,000 × 4KB ≈ 400MB
페이로드 크기:  ~200MB (메타데이터 + 텍스트)
인덱스 오버헤드: ~200MB (HNSW 그래프)
──────────────────────────
총 예상 메모리:  ~800MB ~ 1GB
```

128GB 통합 메모리 중 **1GB 미만** 사용 → 여유롭게 운영 가능.

### 64KB 커널 주의

DGX Spark에서 64KB 커널로 전환하면:
1. NVIDIA 드라이버 모듈 로딩 실패
2. Qdrant jemalloc 페이지 사이즈 불일치 에러

현재 기본 커널(4KB 페이지)을 유지할 것.

---

## 9. 빠른 시작 요약

```bash
# 1. Qdrant 이미지 pull (ARM64 자동 감지)
docker pull qdrant/qdrant:v1.17.0

# 2. 스토리지 디렉토리 생성
mkdir -p /home/gon/ws/rag/qdrant_storage

# 3. 컨테이너 실행
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant:v1.17.0

# 4. 헬스체크
curl http://localhost:6333/healthz

# 5. 검증 스크립트 실행
pip install qdrant-client numpy
python test_qdrant.py
```

---

## 참고 자료

- [Qdrant 공식 설치 가이드](https://qdrant.tech/documentation/guides/installation/)
- [Qdrant Docker Hub](https://hub.docker.com/r/qdrant/qdrant)
- [Qdrant GitHub Releases](https://github.com/qdrant/qdrant/releases)
- [Qdrant ARM64 지원 블로그](https://qdrant.tech/blog/qdrant-supports-arm-architecture/)
- [jemalloc aarch64 이슈 #4298](https://github.com/qdrant/qdrant/issues/4298)
- [ARM64 jemalloc 이슈 #5952](https://github.com/qdrant/qdrant/issues/5952)
- [DGX Spark 64K 커널 이슈 — NVIDIA Forums](https://forums.developer.nvidia.com/t/dgx-spark-64k-kernels/355883)
