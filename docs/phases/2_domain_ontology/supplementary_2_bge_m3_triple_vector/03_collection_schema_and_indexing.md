# Qdrant v2 컬렉션 스키마 + 인덱싱 — 상세 설계

> 목적: BGE-M3의 3종 벡터(Dense+Sparse+ColBERT)를 저장하는 Qdrant 컬렉션 설계 및 인덱싱 스크립트
> 수정 대상: 신규 `codes/embedding/index_phase2_v2.py`
> 기존 `index_phase2.py`의 헬퍼 함수를 재사용하며, 컬렉션 스키마와 벡터 upsert 부분만 변경

---

## 1. 주요 개념 설명

### 1-1. Qdrant Named Vectors

> **개념**: 하나의 포인트(문서)에 **이름이 붙은 여러 벡터**를 동시에 저장하는 기능.

기존 v1 컬렉션(`domain_ontology`)에는 `"dense"`라는 이름의 벡터 1개만 저장했다. v2에서는 하나의 포인트에 3개의 벡터를 저장한다:

```
[포인트 1개]
├── "dense":   [0.12, -0.45, ..., 0.33]           ← 1024차원 벡터 1개
├── "sparse":  {4521: 2.3, 8902: 1.1}              ← 희소 벡터
└── "colbert": [[0.1, ...], [0.2, ...], [0.3, ...]] ← 토큰별 벡터 여러 개
```

### 1-2. MultiVectorConfig와 MAX_SIM

ColBERT 벡터는 **하나의 벡터가 아니라 행렬**(여러 벡터의 목록)이다. 이것을 Qdrant에 저장하려면 `MultiVectorConfig`를 사용한다.

```python
"colbert": VectorParams(
    size=1024,
    distance=Distance.COSINE,
    multivector_config=MultiVectorConfig(
        comparator=MultiVectorComparator.MAX_SIM,  # MaxSim 스코어링
    ),
)
```

- `MultiVectorConfig`: "이 벡터 슬롯에는 벡터가 여러 개 들어간다"고 Qdrant에 알림
- `MAX_SIM`: 검색 시 **MaxSim** 알고리즘을 사용하라는 설정. 쿼리의 각 토큰 벡터에 대해 문서의 모든 토큰 벡터 중 가장 유사한 것을 찾아 합산

### 1-3. hnsw_config(m=0)의 의미

> **개념**: `m=0`은 "이 벡터에 대해 HNSW 인덱스를 만들지 말라"는 뜻.

HNSW(Hierarchical Navigable Small World) 인덱스는 벡터 검색을 빠르게 하는 자료구조다. 하지만 ColBERT 벡터에는 이것이 **불필요하다**:

- ColBERT는 Stage 3(리랭킹)에서만 사용된다
- 리랭킹 시점에는 후보가 이미 50개 이하로 줄어든 상태
- 50개 정도는 brute force(전수 비교)로도 충분히 빠르다 (~5ms)
- HNSW를 만들면 **메모리가 2-3배** 더 필요하다

```python
hnsw_config=HnswConfigDiff(m=0),  # 인덱스 안 만듦 → 메모리 절약
```

### 1-4. INT8 스칼라 양자화(Scalar Quantization)

> **개념**: 32비트 부동소수점(float32) 벡터를 8비트 정수(int8)로 압축하는 기법.

```
float32: 0.7823451... → 4바이트/숫자
int8:    200 (0~255 중) → 1바이트/숫자 (4배 압축)
```

양자화 과정:
1. 벡터 값의 분포를 분석 (예: -1.5 ~ +1.5 범위)
2. 이 범위를 0~255로 매핑 (256단계로 나눔)
3. 각 값을 가장 가까운 정수로 변환

```
원본: [0.12, -0.45, 0.78, 0.03]
양자화: [142, 89, 194, 131]  (0~255 범위)
```

**`quantile=0.99`**: 값의 99%가 포함되는 범위만 사용. 극단값(outlier)은 잘라냄.
**`always_ram=True`**: 양자화된 벡터를 항상 RAM에 유지하여 검색 속도 보장.

ColBERT 벡터에 적용하면:
- float32: 2,146 포인트 × 30 토큰 × 1024 × 4B ≈ **264MB**
- int8: 2,146 × 30 × 1024 × 1B ≈ **66MB** (4배 절약)

---

## 2. v1 vs v2 컬렉션 스키마 비교

### 2-1. domain_ontology

```python
# === v1 (현재) ===
# Dense 벡터 1종만 사용
client.create_collection(
    collection_name="domain_ontology",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
)

# === v2 (신규) ===
# Dense + Sparse + ColBERT 3종 벡터
client.create_collection(
    collection_name="domain_ontology_v2",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
        "colbert": VectorParams(
            size=1024,
            distance=Distance.COSINE,
            multivector_config=MultiVectorConfig(
                comparator=MultiVectorComparator.MAX_SIM,
            ),
            hnsw_config=HnswConfigDiff(m=0),           # 리랭킹 전용
            quantization_config=ScalarQuantization(
                type=ScalarType.INT8,
                quantile=0.99,
                always_ram=True,
            ),
        ),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF),
    },
)
```

### 2-2. legal_docs

```python
# === v1 (현재) ===
# Dense + Sparse(Kiwi BM25) 사용
client.create_collection(
    collection_name="legal_docs",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF),
    },
)

# === v2 (신규) ===
# Dense + Sparse(BGE-M3 학습) + ColBERT 사용
# domain_ontology_v2와 동일한 스키마
```

### 2-3. 차이점 요약

| 항목 | v1 | v2 |
|------|----|----|
| Dense 벡터 | KURE-v1 (1024D) | BGE-M3 (1024D) |
| Sparse 벡터 | Kiwi BM25 (해시 기반 TF) | BGE-M3 Sparse (학습된 어휘 가중치) |
| ColBERT 벡터 | 없음 | BGE-M3 ColBERT (토큰별 1024D) |
| 검색 방식 | Dense only / Dense+Sparse RRF | Dense+Sparse prefetch → ColBERT rerank |

---

## 3. 인덱싱 플로우 비교

### v1 (`index_phase2.py`) 플로우:

```
1. 데이터 로드 (ontology entries + legal docs JSON)
2. 임베딩 텍스트 생성 (term + aliases + description + prefix)
3. KURE-v1 Dense 임베딩 (embedder.embed_texts)
4. [legal only] Kiwi BM25 Sparse 벡터 생성 (sparse_bm25.get_sparse_vectors)
5. PointStruct 생성: vector={"dense": [...]}
6. Qdrant upsert
```

### v2 (`index_phase2_v2.py`) 플로우:

```
1. 데이터 로드 (동일 — index_phase2.py의 함수 재사용)
2. 임베딩 텍스트 생성 (동일 — _build_ontology_text, _expand_legal_chunks 재사용)
3. BGE-M3 3종 벡터 추출 (embedder_bgem3.embed_texts) ← 변경!
4. PointStruct 생성: vector={"dense": [...], "sparse": SparseVector(...), "colbert": [[...]]}
5. Qdrant upsert (배치 크기 50)
```

**핵심 변경**: Step 3에서 `embedder.py` 대신 `embedder_bgem3.py`를 사용하고, Step 4에서 3종 벡터를 모두 포함한다.

---

## 4. PointStruct 구조 비교

### v1 (domain_ontology, Dense only):

```python
PointStruct(
    id="a1b2c3d4-...",
    vector={
        "dense": [0.12, -0.45, ..., 0.33],  # 1024개 float
    },
    payload={
        "entry_id": "tax_acquisition",
        "term": "취득세",
        "level": 2,
        "branch": "tax",
        "aliases": ["집 살 때 세금", ...],
        "text": "취득세 | 다주택자 취득세 중과세율...",
    },
)
```

### v2 (domain_ontology_v2, Triple-Vector):

```python
PointStruct(
    id="a1b2c3d4-...",
    vector={
        "dense": [0.12, -0.45, ..., 0.33],                    # 1024개 float
        "sparse": SparseVector(
            indices=[4521, 8902, 12045, ...],                   # 토큰 ID
            values=[2.301, 1.100, 0.832, ...],                  # 가중치
        ),
        "colbert": [                                            # 토큰별 벡터
            [0.1, 0.2, ..., 0.05],   # 토큰 1의 벡터 (1024D)
            [0.3, -0.1, ..., 0.12],  # 토큰 2의 벡터 (1024D)
            ...,                      # ... 토큰 N개
        ],
    },
    payload={  # 동일
        "entry_id": "tax_acquisition",
        "term": "취득세",
        ...
    },
)
```

---

## 5. 재사용하는 기존 함수

`index_phase2.py`에서 다음 함수들을 import하여 재사용한다:

| 함수 | 역할 | 위치 |
|------|------|------|
| `_build_ontology_text(entry, prefix)` | 온톨로지 엔트리의 임베딩 텍스트 생성 | `index_phase2.py:162` |
| `_expand_legal_chunks(data, prefixes)` | 법률문서 JSON → (type, text, payload) 확장 | `index_phase2.py:276` |
| `_point_id(text)` | 텍스트 기반 결정적 UUID 생성 | `index_phase2.py:152` |
| `_batch_upsert(client, collection, points)` | 배치 단위 Qdrant upsert | `index_phase2.py:143` |
| `_build_hierarchy_path(hierarchy)` | 계층 경로 문자열 생성 | `index_phase2.py:264` |

---

## 6. CLI 인터페이스

```bash
# 전체 색인 (두 컬렉션 모두)
python codes/embedding/index_phase2_v2.py --force

# domain_ontology_v2만
python codes/embedding/index_phase2_v2.py --only ontology --force

# legal_docs_v2만
python codes/embedding/index_phase2_v2.py --only legal --force

# ColBERT 없이 디버깅 (Dense + Sparse만)
python codes/embedding/index_phase2_v2.py --no-colbert --force

# 옵션
python codes/embedding/index_phase2_v2.py \
    --qdrant-url http://qdrant:6333 \
    --model-name BAAI/bge-m3 \
    --batch-size 32 \
    --force
```

---

## 7. 전체 코드

아래는 `codes/embedding/index_phase2_v2.py`의 전체 코드이다.

```python
#!/usr/bin/env python3
"""
index_phase2_v2.py — Phase 2 v2 색인: BGE-M3 Triple-Vector.

domain_ontology_v2 + legal_docs_v2 컬렉션에 Dense+Sparse+ColBERT 3종 벡터를 색인한다.
기존 index_phase2.py의 헬퍼 함수를 재사용하고, 임베딩 모델과 컬렉션 스키마만 변경.
"""
# ... (전체 코드는 codes/embedding/index_phase2_v2.py 파일 참조)
```

---

## 8. 검증 방법

### 8-1. 컨테이너 내부 실행

```bash
docker exec rag-embedding python3 /workspace/codes/embedding/index_phase2_v2.py --force
```

### 8-2. 확인 항목

| 항목 | 기대값 |
|------|--------|
| domain_ontology_v2 포인트 수 | 2,146 |
| legal_docs_v2 포인트 수 | ~976 |
| 두 컬렉션 상태 | `green` |
| 벡터 구성 | dense + sparse + colbert |
| 소요 시간 | ~5-10분 (모델 다운로드 제외) |

### 8-3. Qdrant REST API로 확인

```bash
# 컬렉션 정보
curl -s http://localhost:6333/collections/domain_ontology_v2 | python -m json.tool

# 포인트 1개 조회하여 벡터 구성 확인
curl -s http://localhost:6333/collections/domain_ontology_v2/points/scroll \
  -X POST -H 'Content-Type: application/json' \
  -d '{"limit": 1, "with_vector": ["dense"]}' | python -m json.tool
```
