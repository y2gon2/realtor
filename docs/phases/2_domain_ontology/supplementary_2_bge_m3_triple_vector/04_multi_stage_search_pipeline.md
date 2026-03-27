# Multi-Stage Search Pipeline — 다단계 검색 파이프라인 설계

> 목적: BGE-M3 3종 벡터를 활용한 다단계 검색 파이프라인 구현 및 테스트
> 신규 파일: `codes/embedding/search_test_phase2_v2.py`
> 기존 파일 참고: `codes/embedding/search_test_phase2_extended.py` (45개 질의 재사용)

---

## 1. 검색 파이프라인 구조

### 1-1. 현재 v1 파이프라인 (KURE-v1)

```
domain_ontology:
  쿼리 → KURE-v1 Dense 임베딩 → Dense 검색 → top-5 반환

legal_docs:
  쿼리 → KURE-v1 Dense 임베딩 + Kiwi BM25 Sparse
       → Dense 검색 (top-20) + Sparse 검색 (top-20)
       → RRF 퓨전 → top-5 반환
```

### 1-2. v2 Multi-Stage 파이프라인 (BGE-M3)

```
두 컬렉션 모두 동일한 3단계 파이프라인:

  쿼리 → BGE-M3 임베딩 (Dense + Sparse + ColBERT 동시 생성)
       ↓
  ┌─ Stage 1a: Dense 검색 → top-100 후보
  ├─ Stage 1b: Sparse 검색 → top-100 후보  (1a, 1b 병렬 실행)
  └─ Stage 2: RRF 퓨전 → top-50
       ↓
  Stage 3: ColBERT MaxSim 리랭킹 → top-10 최종 반환
```

### 1-3. Qdrant Query API에서의 구현

Qdrant의 `query_points` API는 **중첩된 `prefetch`**를 지원한다. 이를 통해 위 3단계를 **단일 API 호출**로 수행할 수 있다.

```python
results = client.query_points(
    collection_name="domain_ontology_v2",

    # Stage 1+2: Dense와 Sparse를 각각 prefetch한 뒤 퓨전
    prefetch=[
        Prefetch(query=dense_vec, using="dense", limit=100),
        Prefetch(query=sparse_sv, using="sparse", limit=100),
    ],

    # Stage 3: 퓨전된 후보를 ColBERT로 리랭킹
    query=colbert_vecs,     # 쿼리의 토큰별 벡터 목록
    using="colbert",        # ColBERT 벡터 슬롯 사용
    limit=10,               # 최종 반환 개수

    with_payload=[...],     # 함께 반환할 페이로드 필드
)
```

**동작 원리 (Qdrant 서버 내부)**:
1. `prefetch[0]`: Dense HNSW 인덱스에서 top-100 후보 검색
2. `prefetch[1]`: Sparse 역색인에서 top-100 후보 검색
3. 두 리스트의 합집합을 구한 뒤, 이 후보들에 대해 ColBERT MaxSim 스코어를 계산
4. ColBERT 점수 기준으로 정렬하여 top-10 반환

> **주의**: `prefetch`에 의해 선별된 후보 **합집합**에서만 ColBERT를 수행하므로, Dense나 Sparse 어느 쪽에도 걸리지 않는 문서는 ColBERT 리랭킹 대상에 포함되지 않는다.

---

## 2. Ablation Study(절제 연구) 설계

### 2-1. Ablation이란?

> **개념**: 시스템의 각 구성 요소를 하나씩 제거(절제)하면서 성능 변화를 관찰하는 실험 방법.

의학에서 "절제(ablation)"는 조직을 제거하는 시술을 말한다. AI 연구에서는 모델의 구성 요소를 하나씩 빼면서 "이 부분이 없으면 성능이 얼마나 떨어지는가?"를 측정한다.

예: "ColBERT를 빼면 성능이 10% 떨어진다" → ColBERT의 기여도는 10%

### 2-2. 3가지 Ablation 모드

| 모드 | 벡터 사용 | Qdrant 쿼리 방식 | 목적 |
|------|----------|-----------------|------|
| `dense_only` | Dense만 | `query_points(query=dense, using="dense")` | BGE-M3 Dense vs KURE-v1 Dense 순수 비교 |
| `hybrid_rrf` | Dense + Sparse | `prefetch=[Dense, Sparse], query=FusionQuery(RRF)` | Sparse 추가 효과 측정 |
| `hybrid_colbert` | Dense + Sparse + ColBERT | `prefetch=[Dense, Sparse], query=ColBERT` | **최종 목표 파이프라인** |

### 2-3. 각 모드의 Qdrant 쿼리 구현

#### Mode 1: `dense_only`
```python
# Dense 벡터만으로 검색 (가장 단순)
results = client.query_points(
    collection_name=collection,
    query=dense_vec,
    using="dense",
    limit=limit,
    with_payload=payload_fields,
)
```

#### Mode 2: `hybrid_rrf`
```python
# Dense + Sparse를 RRF로 합산
results = client.query_points(
    collection_name=collection,
    prefetch=[
        Prefetch(query=dense_vec, using="dense", limit=100),
        Prefetch(query=sparse_sv, using="sparse", limit=100),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=limit,
    with_payload=payload_fields,
)
```

#### Mode 3: `hybrid_colbert`
```python
# Dense + Sparse prefetch → ColBERT rerank
results = client.query_points(
    collection_name=collection,
    prefetch=[
        Prefetch(query=dense_vec, using="dense", limit=100),
        Prefetch(query=sparse_sv, using="sparse", limit=100),
    ],
    query=colbert_vecs,
    using="colbert",
    limit=limit,
    with_payload=payload_fields,
)
```

---

## 3. 테스트 질의

기존 `search_test_phase2_extended.py`의 45개 질의를 그대로 재사용한다:

- **온톨로지 25개**: 기존 10개 (직접 표현) + 추가 15개 (추상적 표현)
- **법률 20개**: 기존 8개 (직접 표현) + 추가 12개 (추상적 표현)

Precision@3 판정을 위한 `expected` 키워드 매핑도 동일하게 사용.

---

## 4. 출력 형식

각 질의에 대해 다음 정보를 출력한다:

```
질의: 집 살 때 세금 얼마야
  [1] 0.8234 | 취득세 (세금 > 취득세) | aliases: [집 살 때 세금, ...]
  [2] 0.7912 | 양도소득세 (세금 > 양도세)
  [3] 0.7456 | 재산세 (세금 > 보유세)
```

모드 간 비교표:
```
============================================================
ABLATION 비교 (domain_ontology_v2, 25개 질의)
============================================================
모드            Precision@3  Avg Top-1  Avg Latency
dense_only      80%          0.6812     12ms
hybrid_rrf      88%          0.7234     45ms
hybrid_colbert  92%          0.7891     78ms
```

---

## 5. 전체 코드

아래는 `codes/embedding/search_test_phase2_v2.py`의 전체 구조이다. (실제 코드는 해당 파일 참조)

---

## 6. 검증 방법

```bash
# 전체 Ablation 실행
docker exec rag-embedding python3 /workspace/codes/embedding/search_test_phase2_v2.py --mode all

# ColBERT 모드만 빠르게 확인
docker exec rag-embedding python3 /workspace/codes/embedding/search_test_phase2_v2.py --mode hybrid_colbert
```

### 확인 항목

| 항목 | 기대값 |
|------|--------|
| dense_only Precision@3 | 75-85% (BGE-M3 Dense, KURE-v1보다 약간 낮을 수 있음) |
| hybrid_rrf Precision@3 | 85-90% (Sparse 추가 효과) |
| hybrid_colbert Precision@3 | **90%+** (목표) |
| 레이턴시 p95 | < 200ms |
| JSON 리포트 생성 여부 | `--mode all` 실행 시 JSON 출력 확인 |
