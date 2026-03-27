# 벤치마크 및 Ablation Study — v1 vs v2 A/B 비교

> 목적: KURE-v1(v1 컬렉션)과 BGE-M3 Triple-Vector(v2 컬렉션) 간 정량적 비교
> 신규 파일: `codes/embedding/benchmark_phase2_v2.py`

---

## 1. 벤치마크 설계

### 1-1. 비교 대상

| 설정 | 모델 | 벡터 | 퓨전 방식 | 컬렉션 |
|------|------|------|----------|--------|
| **A (baseline)** | KURE-v1 | Dense + Kiwi BM25 | RRF | domain_ontology + legal_docs |
| **B** | BGE-M3 | Dense + Sparse | RRF | domain_ontology_v2 + legal_docs_v2 |
| **C (target)** | BGE-M3 | Dense + Sparse + ColBERT | Multi-Stage | domain_ontology_v2 + legal_docs_v2 |

### 1-2. 왜 A/B 비교가 필요한가?

새로운 시스템(v2)이 기존(v1)보다 **실제로** 좋은지 확인해야 한다. 단순히 "이론적으로 좋다"가 아니라, **같은 질의에 대해 같은 기준으로 측정**해야 신뢰할 수 있다.

비교에서 주의할 점:
- v1과 v2는 **임베딩 모델이 다르다** (KURE-v1 vs BGE-M3)
- 따라서 검색 점수(score)의 **절대값**을 비교하면 안 된다
- **순위 기반 지표**(Precision@3)와 **상대적 개선폭**으로 비교해야 한다

### 1-3. 측정 지표

| 지표 | 설명 | 계산 방법 |
|------|------|----------|
| **Precision@3** | Top-3 결과 중 관련 결과가 있는 비율 | 기존 `expected` 키워드 매핑으로 자동 판정 |
| **Avg Top-1 Score** | 평균 1위 결과 점수 | 각 질의의 1위 점수를 평균 |
| **Latency p50/p95** | 검색 레이턴시 | 밀리초 단위 측정 |
| **Retrieval Overlap** | v1과 v2의 결과 유사도 | Top-10 결과의 Jaccard similarity |

### 1-4. Jaccard Similarity(자카드 유사도)란?

> **개념**: 두 집합의 교집합 크기를 합집합 크기로 나눈 값. 0(완전 다름) ~ 1(완전 같음).

```
v1 Top-10 = {취득세, 양도세, 재산세, 종부세, 등록세, ...}
v2 Top-10 = {취득세, 양도세, 재산세, 상속세, 증여세, ...}

교집합 = {취득세, 양도세, 재산세} → 3개
합집합 = {취득세, 양도세, 재산세, 종부세, 등록세, 상속세, 증여세, ...} → 7개

Jaccard = 3/7 = 0.43
```

Jaccard가 낮으면 v1과 v2의 결과가 많이 다르다는 뜻이다. 이는 BGE-M3가 **다른 관점으로 검색**하고 있음을 의미한다.

---

## 2. 성공 기준

| 지표 | 현재 (v1, KURE-v1) | 목표 (v2, BGE-M3 Triple) |
|------|-------------------|-------------------------|
| Precision@3 (전체 45개) | 84% | **≥ 90%** |
| Precision@3 (추상 질의 27개) | 80% | **≥ 87%** |
| Avg Top-1 Ontology | 0.619 | **≥ 0.72** |
| Avg Top-1 Legal | 0.612 | **≥ 0.70** |
| Latency p95 | ~50ms | **< 200ms** |

---

## 3. 벤치마크 스크립트 설계

### 3-1. 실행 흐름

```
1. v1 컬렉션 검색 (KURE-v1 임베딩 → domain_ontology + legal_docs)
2. v2 컬렉션 3가지 모드 검색 (BGE-M3 임베딩 → v2 컬렉션)
   - dense_only
   - hybrid_rrf
   - hybrid_colbert
3. 지표 계산 및 비교표 출력
4. JSON 리포트 저장
```

### 3-2. v1 검색 방법

v1 컬렉션은 KURE-v1으로 임베딩되었으므로, v1 검색 시에는 기존 `embedder.py`를 사용한다:

```python
from embedder import embed_texts as kure_embed
from sparse_bm25 import get_sparse_vectors as kiwi_sparse
```

### 3-3. 출력 형식

```
============================================================
BENCHMARK: v1 (KURE-v1) vs v2 (BGE-M3 Triple-Vector)
============================================================

Ontology (25 queries):
설정              Precision@3  Avg Top-1  p50(ms)  p95(ms)
A: v1 KURE+BM25       84%      0.6192     12.3     23.4
B: v2 BGE-M3 D+S      88%      0.7012     45.2     67.8
C: v2 BGE-M3 D+S+C    92%      0.7891     78.4    112.3

Legal (20 queries):
설정              Avg Top-1  p50(ms)  p95(ms)
A: v1 KURE+BM25   0.6119     15.6     28.9
B: v2 BGE-M3 D+S  0.6823     48.7     72.1
C: v2 BGE-M3 D+S+C 0.7345    82.3    118.9

Retrieval Overlap (Jaccard, v1 vs v2-C):
  Ontology: 0.45  (결과가 55% 다름)
  Legal:    0.38  (결과가 62% 다름)
```

---

## 4. 전체 코드

아래는 `codes/embedding/benchmark_phase2_v2.py`의 전체 구조이다. (실제 코드는 해당 파일 참조)

---

## 5. 실행 방법

```bash
# 전체 벤치마크 (v1 + v2 3모드)
docker exec rag-embedding python3 /workspace/codes/embedding/benchmark_phase2_v2.py

# Qdrant URL 변경
docker exec rag-embedding python3 /workspace/codes/embedding/benchmark_phase2_v2.py \
    --qdrant-url http://qdrant:6333
```

---

## 6. 결과 해석 가이드

### 6-1. BGE-M3 Dense가 KURE-v1보다 낮은 경우

- **기대됨**: KURE-v1은 한국어 Dense 전용 fine-tune이므로 Dense 단독 비교에서 더 높을 수 있다
- **중요한 것**: `hybrid_colbert` 모드(전체 파이프라인)에서 v1을 이기는 것
- Sparse의 동의어 확장 + ColBERT의 토큰별 매칭이 Dense 약점을 보상

### 6-2. Precision@3이 목표 미달인 경우

실패 질의를 분석하여:
- **W2 유형** (구어체 격차): BGE-M3 Sparse가 해결하지 못한 극단적 표현 확인
- **W1 유형** (cross-domain): 여러 도메인에 걸친 질의 → P1-a Query Decomposition 필요
- 결과를 `06_results_and_analysis.md`에 기록

### 6-3. Latency가 200ms 초과인 경우

- ColBERT prefetch limit을 100→50으로 줄여볼 것
- `max_length`를 512→256으로 줄여 ColBERT 토큰 수 감소
- INT8 양자화가 적용되었는지 확인
