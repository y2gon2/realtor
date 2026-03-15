# Vector Database 기술 연구 보고서

> 조사일: 2026-03-08
> 프로젝트: 대한민국 부동산 AI 어드바이저 RAG 시스템
> 하드웨어: NVIDIA DGX Spark (GB10, ARM64/aarch64, 128GB unified memory)
> 임베딩 모델: KURE-v1 (1024 dimensions, dense only)
> 데이터 규모: ~20K 문서 (목표 50K+), 한국어 YouTube 부동산 학습 노트

---

## 1. Vector Database 기본 개념

### 1.1 Vector Database란?

Vector Database는 고차원 벡터(embedding)를 효율적으로 저장, 인덱싱, 검색하는 전문 데이터베이스다. 전통적인 관계형 DB가 행/열 기반의 정확한 매칭(exact match)에 최적화된 반면, 벡터 DB는 **의미적 유사도(semantic similarity)** 기반의 근사 최근접 이웃 탐색(ANN: Approximate Nearest Neighbor)에 특화되어 있다.

| 구분 | 전통 DB (RDBMS) | Vector DB |
|------|----------------|-----------|
| 데이터 모델 | 테이블, 행, 열 | 벡터 + 메타데이터 (payload) |
| 쿼리 방식 | SQL, exact match | ANN similarity search |
| 인덱싱 | B-tree, Hash | HNSW, IVF, PQ, DiskANN |
| 결과 | 정확한 일치 | 유사도 순위 (근사치) |
| 활용 | 트랜잭션, 리포팅 | RAG, 추천, 시맨틱 검색 |

### 1.2 핵심 인덱싱 알고리즘

#### HNSW (Hierarchical Navigable Small World)
- **가장 널리 사용되는 ANN 인덱스** (Qdrant, Milvus, Weaviate, pgvector 모두 지원)
- 다층 그래프 구조: 상위 레이어는 성긴 연결(빠른 탐색), 하위 레이어는 밀집 연결(정밀 검색)
- 장점: 높은 recall, 빠른 쿼리, 점진적 업데이트 가능
- 단점: 메모리 사용량 높음 (벡터 + 그래프 구조), 빌드 시간 길 수 있음
- 주요 파라미터: `m` (연결 수), `ef_construction` (빌드 품질), `ef` (검색 품질)

#### IVF (Inverted File Index)
- 벡터를 클러스터링하여 버킷으로 분류 후, 관련 버킷만 검색
- 장점: 메모리 효율적, 대규모 데이터에 적합
- 단점: 클러스터 경계 근처 벡터의 recall 저하 가능
- 변형: IVF-Flat, IVF-PQ, IVF-SQ8

#### PQ (Product Quantization)
- 벡터를 서브벡터로 분할 후 각각을 코드북으로 양자화
- 메모리를 극적으로 절약 (10~50배)하지만 recall 약간 감소
- 보통 IVF나 HNSW와 결합하여 사용

#### DiskANN
- 디스크 기반 인덱싱으로 메모리 제약 환경에서 유리
- VectorChord (pgvecto.rs 후속)가 이 방식을 활용

### 1.3 거리 메트릭 (Distance Metrics)

| 메트릭 | 수식 | 특성 | 사용 사례 |
|--------|------|------|----------|
| **Cosine Similarity** | 1 - cos(a,b) | 방향만 비교, 크기 무관 | 텍스트 임베딩 (가장 일반적) |
| **Euclidean (L2)** | \|\|a-b\|\|_2 | 절대 거리 | 이미지, 좌표 데이터 |
| **Dot Product** | a . b | 크기와 방향 모두 반영 | 정규화된 벡터, 추천 시스템 |

**KURE-v1의 경우**: 텍스트 임베딩 모델이므로 **Cosine Similarity** 권장.

### 1.4 Hybrid Search 아키텍처

Dense 벡터 검색(시맨틱)과 Sparse/BM25 검색(키워드)을 결합하여 retrieval 품질을 극대화하는 방식.

```
Query → ┬─ Dense Encoder (KURE-v1) → Vector Search → Top-K (semantic)
        └─ Sparse/BM25 Tokenizer  → Keyword Search → Top-K (lexical)
                                                          ↓
                                              Score Fusion (RRF/DBSF)
                                                          ↓
                                              Final Re-ranked Results
```

**Score Fusion 방법:**
- **RRF (Reciprocal Rank Fusion)**: 점수 스케일에 무관하게 순위만으로 결합. 가장 안정적.
- **DBSF (Distribution-Based Score Fusion)**: 점수를 정규화한 후 가중합. 알파 파라미터 튜닝 필요.
- **Learned Fusion**: Weaviate 2.0에서 도입. ML 모델이 자동 최적 가중치 학습.

**Hybrid Search의 효과**: 순수 벡터 검색 대비 retrieval precision ~62% → ~84% 향상 (PostgreSQL 벤치마크 기준).

### 1.5 메타데이터 필터링

벡터 검색과 메타데이터 필터를 결합하는 방식:

- **Pre-filtering**: 필터 적용 후 벡터 검색 → 정확하지만 후보가 너무 적으면 recall 저하
- **Post-filtering**: 벡터 검색 후 필터 → recall 손실 가능, 결과 부족 위험
- **In-process filtering**: 검색 중 동시에 필터 적용 (Qdrant ACORN, Milvus 방식) → 최적

**본 프로젝트 필터 필드:**
- `channel_name`: 채널별 필터링 (weolbu_official, Hootv 등)
- `upload_date`: 날짜 범위 필터 (2015~2026)
- `category`: 카테고리 분류
- `keywords`: 키워드 태그

---

## 2. Vector Database 상세 비교 (2025 H2 ~ 2026 Q1)

### 2.1 Qdrant

| 항목 | 내용 |
|------|------|
| **아키텍처** | 독립 서버 (Rust), Docker/K8s 또는 클라우드 |
| **라이선스** | **Apache 2.0** (상업용 자유) |
| **최신 버전** | v1.13+ (2026.03 기준), Python client 1.16.2 |
| **GitHub Stars** | **27,000+** (2025 말 기준) |
| **Hybrid Search** | **네이티브 지원** - Sparse vector + Dense vector, BM25 내장 (v1.15.2+) |
| **BM25** | 서버 사이드 BM25 변환, IDF 자동 적용, stopwords 커스터마이징 |
| **메타데이터 필터** | Payload index 기반, 다양한 타입 지원 (keyword, integer, float, geo, datetime) |
| **Max Dimensions** | 제한 없음 (실용적으로 수천 차원) |
| **ARM64 Docker** | **공식 multi-arch 지원** (linux/amd64 + linux/arm64) |
| **Fusion 방식** | RRF, DBSF 지원 (Query API) |
| **양자화** | Scalar, Product, Binary quantization 지원 |
| **LangChain/LlamaIndex** | 공식 통합 지원 |

**장점:**
- Rust 기반으로 메모리 효율과 성능 모두 우수
- 단일 바이너리, 의존성 없음 (etcd/MinIO 불필요)
- Payload index를 통한 정교한 필터링 + 자동 쿼리 플래닝
- ACORN 알고리즘으로 필터링 시에도 높은 recall 유지
- MMR (Maximal Marginal Relevance) 내장
- 1ms p99 latency (소규모 데이터셋)

**단점:**
- **한국어 BM25 토크나이저 미지원**: CJK 전용 토크나이저가 없음 (Issue #1909, 바이너리 크기 문제로 거부됨)
- 다국어 토크나이저는 있으나, 한국어 형태소 분석 수준의 정밀도는 부족
- **워크어라운드**: 외부 한국어 토크나이저(Kiwi, OKT, Mecab)로 전처리 후 sparse vector로 직접 인덱싱
- Milvus 대비 대규모(억 단위) 처리 경험 부족

**한국어 BM25 워크어라운드:**
```python
# 1. 외부 토크나이저로 한국어 텍스트를 토큰화
# 2. 토큰을 sparse vector로 변환 (BM25 가중치 적용)
# 3. Qdrant에 sparse vector로 직접 저장/검색
# → Qdrant 내장 BM25 대신 외부 파이프라인 구성 필요
```

### 2.2 Milvus / Zilliz

| 항목 | 내용 |
|------|------|
| **아키텍처** | 분산 시스템 (Go + C++), Standalone/Cluster 모드 |
| **라이선스** | **Apache 2.0** (LF AI & Data Foundation) |
| **최신 버전** | v2.6.11 (2026.03 기준) |
| **GitHub Stars** | **40,000+** (2025.12 기준, 최다) |
| **Hybrid Search** | **네이티브 지원** - Sparse-BM25 내장 (v2.5+) |
| **BM25** | 텍스트 입력 → 자동 sparse vector 변환, SPARSE_INVERTED_INDEX |
| **한국어 지원** | **Lindera 토크나이저 (ko-dic)**, ICU 토크나이저, Language Identifier (v2.6+) |
| **메타데이터 필터** | 강력한 스칼라 필터, JSON shredding (100x 가속), geospatial, timestampz |
| **Max Dimensions** | 32,768 |
| **ARM64 Docker** | **ARM64 이미지 제공** (gpu-arm64 포함) |
| **Standalone 의존성** | etcd + MinIO 필요 (Docker Compose로 3개 컨테이너) |
| **LangChain/LlamaIndex** | 공식 통합 지원 |

**장점:**
- **한국어 BM25 최우수 지원**: Lindera ko-dic 형태소 분석 + ICU 토크나이저 + 자동 언어 감지
- 텍스트만 입력하면 BM25 sparse vector 자동 생성 (외부 전처리 불필요)
- 가장 큰 커뮤니티 (40K+ stars, NVIDIA/Salesforce/eBay 등 10,000+ 기업 사용)
- 대규모 확장성 검증됨 (억 단위 벡터)
- Milvus 2.6 Streaming Node로 외부 메시지 큐 불필요
- Int8/RabitQ 양자화로 메모리 50% 절감
- Tiered storage (hot/cold 분리)

**단점:**
- **운영 복잡도**: Standalone도 etcd + MinIO 필요 (3개 컨테이너)
- Qdrant 대비 초기 설정이 복잡
- 고차원 임베딩에서 RPS/latency가 다른 DB 대비 떨어질 수 있음
- Go + C++ 코드베이스로 디버깅 난이도 높음

### 2.3 Weaviate

| 항목 | 내용 |
|------|------|
| **아키텍처** | 독립 서버 (Go), Docker/K8s 또는 클라우드 |
| **라이선스** | **BSD 3-Clause** (상업용 자유) |
| **최신 버전** | v1.30+ |
| **GitHub Stars** | ~12,000 |
| **Hybrid Search** | **네이티브 지원** - BM25 + Vector 내장, Hybrid Search 2.0 (2025.10) |
| **BM25** | 내장, relativeScoreFusion / rankedFusion |
| **한국어 지원** | CJK 지원 이슈 존재 (forum 토론 중) |
| **메타데이터 필터** | 객체 기반 필터링, inverted index |
| **Max Dimensions** | 제한 없음 |
| **ARM64 Docker** | **ARM64 이미지 제공** |
| **LangChain/LlamaIndex** | 공식 통합 지원 |

**장점:**
- Hybrid Search 2.0에서 Learned Fusion 도입 (alpha 튜닝 불필요)
- NDCG@10이 순수 벡터 대비 42% 향상 (Weaviate 벤치마크)
- 단일 바이너리, 의존성 적음
- GraphQL API로 유연한 쿼리

**단점:**
- 50M 벡터 이상에서 메모리/컴퓨트 요구 증가
- CJK/한국어 BM25 토크나이저 지원이 불명확
- Qdrant/Milvus 대비 커뮤니티 규모 작음

### 2.4 Chroma

| 항목 | 내용 |
|------|------|
| **아키텍처** | 임베디드 (Python) + Client/Server 모드 |
| **라이선스** | **Apache 2.0** |
| **GitHub Stars** | ~16,000 |
| **Hybrid Search** | 제한적 (full-text + vector, 정교한 fusion 부족) |
| **한국어 지원** | 기본 토크나이저만 |
| **ARM64 Docker** | 미확인 (Python 기반이므로 호환 가능성 높음) |

**장점:**
- 가장 빠른 프로토타이핑 (몇 줄의 코드)
- LangChain과의 기본 통합이 가장 간편
- Rust 재작성으로 쓰기 성능 4배 향상

**단점:**
- **프로덕션 미성숙**: 클러스터링, 인증, 관측성, 하이브리드 스코어링 부족
- 메모리 누수 보고
- 대규모 데이터셋에서 성능 이슈
- **프로토타이핑/학습용으로만 권장**

### 2.5 Pinecone

| 항목 | 내용 |
|------|------|
| **아키텍처** | **클라우드 전용 (SaaS)** - 자체 호스팅 불가 |
| **라이선스** | **프로프라이어터리** |
| **가격** | Starter 무료, Standard $50/월~, RU 기반 과금 |
| **Hybrid Search** | 지원 (semantic + keyword) |
| **성능** | 20-100ms latency, 수십억 벡터 지원 |

**장점:**
- 운영 부담 제로 (완전 관리형)
- 내장 임베딩/리랭킹 모델
- Dedicated Read Nodes (2025)로 비용 예측 가능

**단점:**
- **자체 호스팅 불가** → DGX Spark 로컬 배포 불가
- 프로프라이어터리 라이선스
- 데이터 주권 이슈 (한국 데이터 해외 저장)
- 비용이 규모에 따라 급증
- **본 프로젝트에 부적합 (자체 호스팅 필수)**

### 2.6 pgvector / pgvecto.rs / VectorChord

| 항목 | pgvector | VectorChord (pgvecto.rs 후속) |
|------|----------|------------------------------|
| **타입** | PostgreSQL 확장 | PostgreSQL 확장 |
| **라이선스** | PostgreSQL License | Apache 2.0 |
| **Max Dimensions** | 2,000 | 65,535 |
| **인덱스** | HNSW, IVFFlat | vchordrq (disk-based), HNSW |
| **Hybrid Search** | SQL FTS + vector (수동 구성) | SQL FTS + vector (수동 구성) |
| **성능 (50M)** | 471 QPS at 99% recall (pgvectorscale) | pgvector HNSW 대비 3x 빠른 쿼리, 16x 빠른 삽입 |
| **100M 인덱싱** | 느림 | **20분** (hierarchical K-means) |

**장점:**
- PostgreSQL 에코시스템 활용 (PostGIS, 실거래가 DB와 통합)
- 벡터 + 관계형 데이터를 하나의 DB에서 관리
- ParadeDB와 결합하면 BM25 hybrid search 가능
- VectorChord: $1에 40만 벡터 저장 가능

**단점:**
- Hybrid search 구성이 수동적 (RRF 직접 구현 필요)
- 전용 벡터 DB 대비 기능 부족 (MMR, 고급 fusion 등)
- PostgreSQL 운영 오버헤드

### 2.7 LanceDB

| 항목 | 내용 |
|------|------|
| **아키텍처** | **임베디드** (SQLite처럼 라이브러리로 사용) |
| **라이선스** | **Apache 2.0** |
| **저장** | Apache Arrow 컬럼형 포맷, S3 호환, 디스크 기반 |
| **Hybrid Search** | BM25 + Vector (FTS 내장) |
| **ARM64** | pre-built wheel 제공 (aarch64) |
| **GPU** | GPU 인덱스 빌드 지원 |

**장점:**
- 서버 불필요 (임베디드 = 운영 복잡도 최소)
- Zero-copy 연산, 자동 버전 관리
- S3에 직접 저장/쿼리 가능 (서버리스)
- 멀티모달 (텍스트, 이미지, 비디오)

**단점:**
- 상대적으로 신생 프로젝트
- 대규모 프로덕션 사례 부족
- Client/Server 모드 제한적
- 한국어 BM25 토크나이저 정보 부족

### 2.8 주목할 신규 진입자

#### TurboPuffer
- S3 기반 저장으로 100x 비용 절감 ($0.02/GB vs 인메모리 $2+/GB)
- Cursor, Notion, Linear 등이 프로덕션 사용
- BM25 + vector hybrid search 지원
- 클라우드 서비스 전용, 자체 호스팅 불가

#### VectorChord
- pgvecto.rs의 후속, PostgreSQL 확장
- pgvector 호환 문법 + 극적인 성능 향상
- 디스크 기반 인덱싱으로 메모리 효율적

---

## 3. 종합 비교표

| 기준 | Qdrant | Milvus | Weaviate | Chroma | Pinecone | pgvector | LanceDB |
|------|--------|--------|----------|--------|----------|----------|---------|
| **라이선스** | Apache 2.0 | Apache 2.0 | BSD-3 | Apache 2.0 | 프로프라이어터리 | PostgreSQL | Apache 2.0 |
| **자체 호스팅** | O | O | O | O | **X** | O | O |
| **ARM64 Docker** | **공식** | **공식** | **공식** | 미확인 | N/A | O | wheel 제공 |
| **Hybrid Search** | **네이티브** | **네이티브** | **네이티브** | 제한적 | 네이티브 | 수동 | FTS 내장 |
| **한국어 BM25** | **X** (외부 필요) | **O** (Lindera ko-dic) | 미확인 | X | N/A | SQL FTS | 미확인 |
| **운영 복잡도** | **낮음** (단일) | 중간 (3컨테이너) | 낮음 (단일) | 낮음 | 없음 | 중간 | **최저** (임베디드) |
| **메타데이터 필터** | **최우수** | 우수 | 우수 | 기본 | 우수 | SQL | 기본 |
| **커뮤니티** | 27K stars | **40K stars** | 12K | 16K | N/A | 13K | 5K |
| **대규모 검증** | 중간 | **최대** | 중간 | 낮음 | 최대 | 중간 | 낮음 |
| **성능 (소규모)** | **최우수** | 우수 | 양호 | 양호 | 우수 | 양호 | 양호 |
| **DGX Spark 적합** | **높음** | 높음 | 높음 | 낮음 | **불가** | 중간 | 높음 |

---

## 4. 한국어 Hybrid Search 전략

### 핵심 과제
한국어는 교착어로 공백 기반 토크나이징이 비효율적. 형태소 분석이 BM25 성능에 결정적 영향.

### 한국어 토크나이저 벤치마크 (AutoRAG)
| 토크나이저 | BM25 성능 | 비고 |
|-----------|----------|------|
| **Kiwi** | **최우수** | 한국어 문서에 강력 권장 |
| OKT | 우수 | Open Korean Text |
| KKma | 양호 | 느리지만 정확 |
| Space | 최저 | 공백 분리만 |

### DB별 한국어 BM25 처리 전략

**Option A: Milvus 네이티브 (권장)**
```
한국어 텍스트 → Milvus Lindera ko-dic 토크나이저 → 자동 BM25 sparse vector
                                                    → 별도 전처리 불필요
```

**Option B: Qdrant + 외부 토크나이저**
```
한국어 텍스트 → Kiwi/OKT 토크나이저 → 토큰 → BM25 가중치 계산 → sparse vector
            → Qdrant sparse vector field에 직접 저장
```

**Option C: PostgreSQL + 외부 토크나이저**
```
한국어 텍스트 → Kiwi/OKT → tsvector 생성 → PostgreSQL FTS
            + KURE-v1 → pgvector dense search
            → RRF fusion (SQL query)
```

---

## 5. DGX Spark 배포 고려사항

### NVIDIA DGX Spark 스펙
- **CPU**: NVIDIA GB10 Grace Blackwell Superchip (ARM64)
- **메모리**: 128GB unified memory
- **AI 성능**: 1 PFLOP FP4
- **네트워킹**: ConnectX-7
- **지원 소프트웨어**: PyTorch, vLLM, SGLang, llama.cpp, LlamaIndex

### 벡터 DB 배포 시나리오

**20K~50K 문서, 1024 차원 기준:**
- 벡터 저장: ~50K x 1024 x 4bytes = ~200MB (dense만)
- + 메타데이터, 인덱스 오버헤드: ~1-2GB 예상
- 128GB 메모리 중 극히 일부만 사용 → **모든 DB가 충분히 여유**

### ARM64 Docker 호환성 요약
| DB | ARM64 Docker | DGX Spark 호환 | 비고 |
|----|-------------|---------------|------|
| Qdrant | 공식 multi-arch | **검증됨** | 가장 간편 |
| Milvus | ARM64 이미지 존재 | **가능** (주의 필요) | page size 이슈 보고 있음 |
| Weaviate | ARM64 이미지 존재 | **가능** | 일부 종속성 빌드 느릴 수 있음 |
| LanceDB | Python wheel 제공 | **가능** | 서버 불필요 |

---

## 6. 최종 권장

### Primary 추천: **Qdrant** (유지)

기존 선택인 Qdrant를 **유지하되**, 한국어 BM25를 외부 파이프라인으로 처리하는 전략을 권장한다.

**선택 근거:**

1. **운영 단순성**: 단일 Docker 컨테이너, 외부 의존성 없음 (Milvus는 etcd+MinIO 필요)
2. **ARM64 공식 지원**: DGX Spark에서 가장 검증된 배포
3. **메타데이터 필터링 최우수**: Payload index + 자동 쿼리 플래닝이 부동산 메타데이터(채널, 날짜, 카테고리) 필터링에 최적
4. **Rust 기반 성능**: 소규모(~50K) 데이터에서 1ms p99 latency
5. **라이선스**: Apache 2.0 (완전 상업용 자유)
6. **네이티브 Hybrid Search**: Dense + Sparse vector 동시 저장/검색, RRF/DBSF fusion 내장
7. **LangChain/LlamaIndex 공식 통합**

**한국어 BM25 해결 전략:**
```python
# 외부 파이프라인으로 해결
from kiwipiepy import Kiwi
kiwi = Kiwi()

def korean_tokenize(text: str) -> dict[str, float]:
    """한국어 텍스트 → BM25 sparse vector"""
    tokens = kiwi.tokenize(text)
    # token frequency → BM25 weight 계산
    # → Qdrant sparse vector로 저장
    return sparse_vector

# Qdrant에 dense + sparse 동시 저장
qdrant.upsert(
    collection_name="real_estate_notes",
    points=[{
        "id": doc_id,
        "vector": {
            "dense": kure_embedding,      # KURE-v1 1024d
            "sparse": korean_bm25_vector  # 외부 토큰화
        },
        "payload": {
            "channel_name": "weolbu_official",
            "upload_date": "2025-03-15",
            "category": "아파트 투자",
            "keywords": ["강남", "재건축", "시세"]
        }
    }]
)
```

### Alternative 추천: **Milvus** (한국어 우선시)

한국어 BM25의 **네이티브 지원**이 가장 중요한 요구사항이라면 Milvus가 더 나은 선택이다.

**Milvus 선택 시 장점:**
- Lindera ko-dic으로 한국어 형태소 분석 내장
- 텍스트만 넣으면 BM25 자동 처리 (외부 파이프라인 불필요)
- v2.6 ICU 토크나이저 + 자동 언어 감지
- 가장 큰 커뮤니티 및 엔터프라이즈 검증

**Milvus 선택 시 트레이드오프:**
- Docker Compose로 3개 컨테이너 관리 (milvus + etcd + minio)
- 초기 설정 복잡도 높음
- ARM64에서 page size 이슈 가능성 (테스트 필요)

### 판단 기준표

| 우선순위 | Qdrant 선택 | Milvus 선택 |
|---------|------------|------------|
| 운영 단순성 우선 | **O** | |
| 한국어 BM25 네이티브 | | **O** |
| 메타데이터 필터링 정교함 | **O** | |
| 외부 파이프라인 구축 의향 | **O** | |
| 최소 설정으로 빠른 시작 | | **O** |
| Phase 2+ 확장 (실거래 DB) | pgvector 병행 | pgvector 병행 |

---

## 7. 향후 과제

1. **DGX Spark 실측 테스트**: Qdrant와 Milvus를 DGX Spark에서 실제 배포하여 ARM64 호환성 및 성능 검증
2. **한국어 BM25 파이프라인 구축**: Kiwi 토크나이저 + Qdrant sparse vector 통합 파이프라인 개발 및 품질 평가
3. **KURE-v1 + BM25 Hybrid 품질 벤치마크**: 부동산 도메인 쿼리로 dense only vs hybrid 성능 비교
4. **Phase 2 PostgreSQL 통합 설계**: 실거래가/건축물대장 관계형 데이터와 벡터 검색의 통합 아키텍처

---

## Sources

### Vector DB 비교 및 벤치마크
- [Best Vector Databases in 2026: Complete Comparison Guide](https://www.firecrawl.dev/blog/best-vector-databases)
- [Vector Database Comparison 2025: Complete Guide](https://tensorblue.com/blog/vector-database-comparison-pinecone-weaviate-qdrant-milvus-2025)
- [Top 9 Vector Databases as of March 2026](https://www.shakudo.io/blog/top-9-vector-databases)
- [VectorDBBench Leaderboard](https://zilliz.com/vdbbench-leaderboard?dataset=vectorSearch)
- [Qdrant Benchmarks](https://qdrant.tech/benchmarks/)
- [10 Reproducible Benchmarks for Milvus, Qdrant & Weaviate](https://medium.com/@Nexumo_/10-reproducible-benchmarks-for-milvus-qdrant-weaviate-02723160b89d)

### Qdrant
- [Qdrant GitHub](https://github.com/qdrant/qdrant)
- [Qdrant Hybrid Search API](https://qdrant.tech/articles/hybrid-search/)
- [Qdrant BM25 Sparse Vectors](https://qdrant.tech/articles/sparse-vectors/)
- [Qdrant 2025 Recap](https://qdrant.tech/blog/2025-recap/)
- [Qdrant 1.15 - Multilingual Tokenization](https://qdrant.tech/blog/qdrant-1.15.x/)
- [Qdrant CJK Tokenizer Issue #1909](https://github.com/qdrant/qdrant/issues/1909)
- [Qdrant Payload Filtering Guide](https://qdrant.tech/articles/vector-search-filtering/)
- [Qdrant Docker Hub (ARM64)](https://hub.docker.com/r/qdrant/qdrant)

### Milvus
- [Milvus GitHub Releases](https://github.com/milvus-io/milvus/releases)
- [Milvus 2.6 Multilingual Full-Text Search](https://milvus.io/blog/how-milvus-26-powers-hybrid-multilingual-search-at-scale.md)
- [Milvus Multi-language Analyzers](https://milvus.io/docs/multi-language-analyzers.md)
- [Milvus Lindera Tokenizer (Korean)](https://milvus.io/docs/lindera-tokenizer.md)
- [Milvus Hybrid Search](https://milvus.io/docs/multi-vector-search.md)
- [Milvus 40K GitHub Stars](https://finance.yahoo.com/news/milvus-surpasses-40-000-github-010000562.html)
- [Milvus Docker Standalone](https://milvus.io/docs/install_standalone-docker.md)

### Weaviate
- [Weaviate Hybrid Search 2.0](https://app.ailog.fr/en/blog/news/weaviate-hybrid-search-2)
- [Weaviate BM25 Keyword Search](https://docs.weaviate.io/weaviate/search/bm25)
- [Weaviate CJK BM25 Forum](https://forum.weaviate.io/t/bm25-cjk-chinese-japanese-korean-support/5762)
- [Weaviate Docker Hub (ARM64)](https://hub.docker.com/r/semitechnologies/weaviate)

### PostgreSQL Vector
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [VectorChord GitHub (pgvecto.rs 후속)](https://github.com/tensorchord/VectorChord)
- [VectorChord vs pgvector Comparison](https://docs.vectorchord.ai/faqs/comparison-pgvector.html)
- [ParadeDB Hybrid Search in PostgreSQL](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)

### LanceDB
- [LanceDB Official](https://lancedb.com/)
- [LanceDB GitHub](https://github.com/lancedb/lancedb)
- [LanceDB Full-Text Search](https://lancedb.com/docs/search/full-text-search/)

### 기타
- [TurboPuffer Architecture](https://jxnl.co/writing/2025/09/11/turbopuffer-object-storage-first-vector-database-architecture/)
- [Korean BM25 Tokenizer Benchmark (AutoRAG)](https://medium.com/@autorag/making-benchmark-of-different-tokenizer-in-bm25-134f2f0e72f8)
- [KURE-v1 on Hugging Face](https://huggingface.co/nlpai-lab/KURE-v1)
- [DGX Spark User Guide](https://docs.nvidia.com/dgx/dgx-spark/)
- [DGX Spark Software Optimizations](https://developer.nvidia.com/blog/new-software-and-model-optimizations-supercharge-nvidia-dgx-spark/)
- [Build Modern RAG Pipeline 2026: Qdrant Hybrid](https://medium.com/@yohanesegipratama/build-a-modern-rag-pipeline-in-2026-docling-qdrant-hybrid-bm25-dense-ai-agent-2e9ac3ccc990)
