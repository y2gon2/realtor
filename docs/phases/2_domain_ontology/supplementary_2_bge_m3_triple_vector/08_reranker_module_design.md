# Cross-Encoder Reranker 모듈 설계 (`reranker.py`)

> 목적: Dense+Sparse RRF 검색 결과를 Cross-Encoder로 리랭킹하는 모듈 설계
> 패턴 원본: `codes/embedding/embedder_bgem3.py` (Singleton 패턴, FP16 최적화)
> 선행 문서: `07_colbert_improvement_research.md` Strategy C

---

## 1. 전체 구조

### Cross-Encoder란?

검색 시스템에서 "reranker(리랭커)"는 1차 검색 결과를 더 정밀하게 재정렬하는 2차 평가 모델이다. 두 가지 대표적 접근법이 있다:

> **쉬운 비유 — 두 가지 면접 방식:**
>
> - **Bi-Encoder (현재 Dense/Sparse/ColBERT)**: 지원자와 직무기술서를 각각 **따로** 요약한 뒤, 요약본끼리 비교한다. 빠르지만(O(1) — 미리 계산해둔 벡터끼리 비교), 세밀한 맥락을 놓칠 수 있다.
>
> - **Cross-Encoder (이번에 도입)**: 지원자 이력서와 직무기술서를 **나란히 놓고 한 줄 한 줄 대조**하면서 적합도를 판단한다. Transformer의 self-attention이 양쪽 텍스트의 모든 토큰 쌍을 비교하므로, "집 살 때 세금"과 "취득세" 같은 표면적으로 다른 표현도 **문맥 안에서** 연결할 수 있다. 대신 쿼리-문서 쌍마다 forward pass가 필요하므로 느리다(O(n)).
>
> 따라서 Cross-Encoder는 전체 컬렉션(2,146건)을 다 보는 것이 아니라, 1차 검색(RRF)이 걸러낸 **top-50 후보만** 재평가한다.

### 파일 역할

```
codes/embedding/
  ├── embedder_bgem3.py          # BGE-M3 3종 벡터 추출 (기존)
  ├── reranker.py                # Cross-Encoder 리랭커 (신규) ← 이 문서
  ├── search_test_phase2_v2.py   # 검색 테스트 (수정)
  └── benchmark_phase2_v2.py     # 벤치마크 (수정)
```

### `reranker.py` 전체 골격

```python
#!/usr/bin/env python3
"""
Cross-Encoder Reranker 모듈

Qdrant Dense+Sparse RRF 검색 결과를 Cross-Encoder로 리랭킹한다.
기본 모델: dragonkue/bge-reranker-v2-m3-ko (Korean fine-tuned, 568M params)

사용 예시:
    from reranker import rerank_results
    reranked = rerank_results(query_text, qdrant_results, top_k=10)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from FlagEmbedding import FlagReranker


# ─────────────────────────── 상수 ───────────────────────────

DEFAULT_MODEL = "dragonkue/bge-reranker-v2-m3-ko"
USE_FP16 = True           # FP16으로 메모리 절반 (~2GB → ~1GB)
DEFAULT_TOP_K = 10        # 리랭킹 후 반환할 결과 수
PAYLOAD_TEXT_KEY = "embedding_text"  # Qdrant payload에서 텍스트를 꺼낼 키


# ─────────────────── 데이터 클래스 ───────────────────────────

@dataclass
class RerankResult:
    """리랭킹 결과 하나."""
    id: str | int
    score: float              # Cross-Encoder sigmoid 스코어 [0, 1]
    original_score: float     # Qdrant RRF 원본 스코어
    original_rank: int        # Qdrant RRF 원본 순위 (0-based)
    payload: dict = field(default_factory=dict)


@dataclass
class RerankOutput:
    """리랭킹 전체 결과."""
    results: list[RerankResult]
    elapsed_sec: float
    model_name: str
    query: str
    candidates_count: int     # 리랭킹 대상 후보 수
```

---

## 2. Reranker 클래스

### 2-1. 모델 로딩 (Singleton 패턴)

> **쉬운 설명 — Singleton 패턴이란?**
>
> 대학 학생식당이 캠퍼스에 **딱 하나**만 있는 것처럼, 무거운 AI 모델도 메모리에 **딱 한 번**만 로드한다. 검색 요청이 100번 들어와도 매번 새로 로드하지 않고, 처음 로드한 모델을 계속 재사용한다.
>
> `embedder_bgem3.py`의 `_get_model()` 패턴과 동일하다.

```python
# ─────────────────── Singleton 모델 관리 ────────────────────

_reranker: FlagReranker | None = None


def _get_reranker(model_name: str = DEFAULT_MODEL) -> FlagReranker:
    """Reranker 모델 로드 (Singleton — 최초 1회만 로드)."""
    global _reranker
    if _reranker is None:
        print(f"[reranker] 모델 로딩 중: {model_name} (FP16={USE_FP16})")
        t0 = time.time()
        _reranker = FlagReranker(model_name, use_fp16=USE_FP16)
        print(f"[reranker] 로드 완료 ({time.time() - t0:.1f}초)")
    return _reranker
```

**모델 로드 시간**: 약 5~10초 (첫 호출 시). 이후 호출은 0ms.

**GPU 메모리**: FP16 기준 약 1.5~2GB. BGE-M3(~3GB)와 동시 로드 시 총 ~5GB. DGX Spark(128GB)에서 충분.

---

### 2-2. `rerank_results()` — 핵심 리랭킹 함수

```python
def rerank_results(
    query: str,
    points: list[Any],          # Qdrant ScoredPoint 리스트
    top_k: int = DEFAULT_TOP_K,
    model_name: str = DEFAULT_MODEL,
    text_key: str = PAYLOAD_TEXT_KEY,
) -> RerankOutput:
    """
    Qdrant 검색 결과를 Cross-Encoder로 리랭킹.

    Args:
        query: 사용자 질의 텍스트
        points: Qdrant client.query_points()의 반환 결과 (.points)
        top_k: 리랭킹 후 반환할 결과 수
        model_name: Cross-Encoder 모델 이름
        text_key: payload에서 텍스트를 꺼낼 키

    Returns:
        RerankOutput: 리랭킹된 결과 + 메타데이터
    """
    if not points:
        return RerankOutput(
            results=[], elapsed_sec=0.0,
            model_name=model_name, query=query, candidates_count=0,
        )

    reranker = _get_reranker(model_name)
    t0 = time.time()

    # ── Step 1: 쿼리-문서 쌍 구성 ──
    pairs = []
    valid_indices = []  # payload에 텍스트가 있는 항목만
    for i, point in enumerate(points):
        text = point.payload.get(text_key, "")
        if text:
            pairs.append([query, text])
            valid_indices.append(i)

    if not pairs:
        return RerankOutput(
            results=[], elapsed_sec=time.time() - t0,
            model_name=model_name, query=query,
            candidates_count=len(points),
        )

    # ── Step 2: Cross-Encoder 스코어 계산 ──
    # normalize=True → sigmoid 적용 → [0, 1] 범위
    scores = reranker.compute_score(pairs, normalize=True)

    # compute_score는 단일 쌍이면 float, 여러 쌍이면 list를 반환
    if isinstance(scores, (int, float)):
        scores = [scores]

    # ── Step 3: 스코어 기준 재정렬 ──
    scored_items = []
    for idx, score in zip(valid_indices, scores):
        point = points[idx]
        scored_items.append(RerankResult(
            id=point.id,
            score=float(score),
            original_score=float(point.score) if point.score else 0.0,
            original_rank=idx,
            payload=point.payload,
        ))

    scored_items.sort(key=lambda x: x.score, reverse=True)
    results = scored_items[:top_k]

    elapsed = time.time() - t0
    return RerankOutput(
        results=results,
        elapsed_sec=elapsed,
        model_name=model_name,
        query=query,
        candidates_count=len(points),
    )
```

> **코드 흐름 설명:**
>
> 1. Qdrant에서 받은 `points` (RRF top-50)에서 각 문서의 텍스트를 추출한다.
> 2. `[query, document_text]` 쌍의 리스트를 만든다.
> 3. `FlagReranker.compute_score()`가 각 쌍에 대해 Cross-Encoder forward pass를 수행하고, `normalize=True` 옵션으로 sigmoid를 적용하여 **[0, 1] 범위의 점수**를 반환한다.
> 4. 점수 기준으로 내림차순 정렬하고 top-k를 반환한다.

---

### 2-3. 배치 처리 + 에러 핸들링

```python
def rerank_batch(
    queries: list[str],
    points_list: list[list[Any]],
    top_k: int = DEFAULT_TOP_K,
    model_name: str = DEFAULT_MODEL,
    text_key: str = PAYLOAD_TEXT_KEY,
) -> list[RerankOutput]:
    """
    여러 쿼리의 검색 결과를 배치로 리랭킹.

    벤치마크 스크립트에서 45개 질의를 한 번에 처리할 때 사용.
    """
    results = []
    for query, points in zip(queries, points_list):
        try:
            output = rerank_results(
                query=query,
                points=points,
                top_k=top_k,
                model_name=model_name,
                text_key=text_key,
            )
            results.append(output)
        except Exception as e:
            print(f"[reranker] 리랭킹 실패: {query[:30]}... → {e}")
            # 실패 시 빈 결과 반환 (전체 배치가 중단되지 않도록)
            results.append(RerankOutput(
                results=[], elapsed_sec=0.0,
                model_name=model_name, query=query,
                candidates_count=len(points),
            ))

    return results
```

---

## 3. 검색 파이프라인 통합 (`search_test_phase2_v2.py` 수정)

### 3-1. 기존 모드 유지

현재 `search_test_phase2_v2.py`의 검색 모드:

| 모드 | 설명 | 설정 |
|------|------|------|
| `dense_only` | Dense 벡터만 사용 | B |
| `hybrid_rrf` | Dense + Sparse RRF | C |
| `hybrid_colbert` | Dense + Sparse → ColBERT rerank | D |

### 3-2. 신규 모드: `hybrid_rrf_rerank` (설정 E)

> **쉬운 설명 — 파이프라인 구조:**
>
> ```
> [Qdrant] D+S RRF → top-50 후보 (빠른 1차 선별)
>                 ↓
> [Client] Cross-Encoder → top-10 최종 결과 (정밀 2차 평가)
> ```
>
> 식당에서 메뉴를 고르는 과정에 비유하면: 1차로 카테고리별 인기 메뉴 50개를 뽑고(RRF), 2차로 푸드 크리틱(Cross-Encoder)이 50개를 직접 맛보고 최종 10개를 선정한다.

```python
from reranker import rerank_results

def search_ontology(client, collection, dense_vec, sparse_sv,
                     colbert_vecs, mode, limit=5, query_text=""):
    """온톨로지 검색 (모드별 분기)."""

    if mode == "dense_only":
        # ... 기존 코드 ...

    elif mode == "hybrid_rrf":
        # ... 기존 코드 ...

    elif mode == "hybrid_colbert":
        # ... 기존 코드 ...

    elif mode == "hybrid_rrf_rerank":
        # ── 설정 E: D+S RRF + Cross-Encoder Reranking ──
        # Step 1: Qdrant에서 RRF top-50 추출
        rrf_results = client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vec, using="dense", limit=100),
                Prefetch(query=sparse_sv, using="sparse", limit=100),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=50,                       # reranker에 넉넉히 전달
            with_payload=True,              # 텍스트 포함 필수
        ).points

        # Step 2: Cross-Encoder 리랭킹
        rerank_output = rerank_results(
            query=query_text,
            points=rrf_results,
            top_k=limit,
        )

        # Step 3: RerankResult → ScoredPoint 호환 형태로 변환
        return _convert_rerank_to_points(rerank_output.results)

    elif mode == "three_way_rrf":
        # ── 설정 F: D+S+ColBERT 3-Way RRF ──
        return client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vec, using="dense", limit=50),
                Prefetch(query=sparse_sv, using="sparse", limit=50),
                Prefetch(query=colbert_vecs, using="colbert", limit=50),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=payload_fields,
        ).points
```

### 3-3. 헬퍼 함수

```python
def _convert_rerank_to_points(rerank_results: list) -> list:
    """RerankResult를 기존 벤치마크 코드와 호환되는 형태로 변환."""

    class PointLike:
        """ScoredPoint 호환 경량 객체."""
        def __init__(self, r):
            self.id = r.id
            self.score = r.score           # Cross-Encoder 점수 [0, 1]
            self.payload = r.payload

    return [PointLike(r) for r in rerank_results]
```

---

## 4. 벤치마크 스크립트 확장 (`benchmark_phase2_v2.py` 수정)

### 4-1. 설정 E, F 추가

```python
# benchmark_phase2_v2.py 상단의 설정 정의에 추가:

SETTINGS = {
    "A": {"desc": "v1 KURE-v1 + Kiwi BM25", "mode": "hybrid_rrf",
          "collection_suffix": ""},
    "B": {"desc": "v2 BGE-M3 Dense only", "mode": "dense_only",
          "collection_suffix": "_v2"},
    "C": {"desc": "v2 BGE-M3 D+S RRF", "mode": "hybrid_rrf",
          "collection_suffix": "_v2"},
    "D": {"desc": "v2 BGE-M3 D+S+ColBERT", "mode": "hybrid_colbert",
          "collection_suffix": "_v2"},
    # ── 신규 ──
    "E": {"desc": "v2 BGE-M3 D+S RRF + Cross-Encoder",
          "mode": "hybrid_rrf_rerank",
          "collection_suffix": "_v2"},
    "F": {"desc": "v2 BGE-M3 D+S+ColBERT 3-Way RRF",
          "mode": "three_way_rrf",
          "collection_suffix": "_v2"},
}
```

### 4-2. 벤치마크 실행 흐름

```python
def run_benchmark(settings_to_test: list[str] = None):
    """지정된 설정들에 대해 벤치마크 실행."""
    if settings_to_test is None:
        settings_to_test = ["C", "E", "F"]  # 기본: 핵심 3개 비교

    for setting_key in settings_to_test:
        setting = SETTINGS[setting_key]
        print(f"\n{'='*60}")
        print(f"설정 {setting_key}: {setting['desc']}")
        print(f"{'='*60}")

        mode = setting["mode"]
        collection = f"domain_ontology{setting['collection_suffix']}"

        results = []
        latencies = []

        for query_info in TEST_QUERIES:
            t0 = time.time()

            # 임베딩 (모든 설정 공통)
            dense_vec, sparse_sv, colbert_vecs = embed_query(query_info["text"])

            # 검색 (모드별 분기)
            points = search_ontology(
                client, collection,
                dense_vec, sparse_sv, colbert_vecs,
                mode=mode,
                limit=5,
                query_text=query_info["text"],  # reranker용
            )

            latency = time.time() - t0
            latencies.append(latency)

            # 결과 기록
            results.append({
                "query": query_info["text"],
                "top1_term": points[0].payload.get("term", "?") if points else "?",
                "top1_score": points[0].score if points else 0,
                "precision_at_3": evaluate_precision(points[:3], query_info),
            })

        # 요약 출력
        avg_top1 = sum(r["top1_score"] for r in results) / len(results)
        p_at_3 = sum(r["precision_at_3"] for r in results) / len(results)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        print(f"  P@3: {p_at_3:.0%}")
        print(f"  Avg Top-1: {avg_top1:.4f}")
        print(f"  Latency p95: {p95_latency*1000:.0f}ms")
```

---

## 5. 출력 포맷

### 5-1. 콘솔 출력 예시

```
============================================================
설정 C: v2 BGE-M3 D+S RRF
============================================================
  P@3: 92%
  Avg Top-1: 0.7907
  Latency p95: 48ms

============================================================
설정 E: v2 BGE-M3 D+S RRF + Cross-Encoder
============================================================
[reranker] 모델 로딩 중: dragonkue/bge-reranker-v2-m3-ko (FP16=True)
[reranker] 로드 완료 (6.2초)
  P@3: 94%
  Avg Top-1: 0.8234
  Latency p95: 285ms

============================================================
설정 F: v2 BGE-M3 D+S+ColBERT 3-Way RRF
============================================================
  P@3: 90%
  Avg Top-1: 0.0312
  Latency p95: 55ms
```

### 5-2. 벤치마크 결과 JSON 예시

```json
{
  "benchmark_date": "2026-03-28",
  "settings": {
    "C": {
      "description": "v2 BGE-M3 D+S RRF",
      "precision_at_3": 0.92,
      "avg_top1_ontology": 0.7907,
      "avg_top1_legal": 0.7338,
      "latency_p95_ms": 48
    },
    "E": {
      "description": "v2 BGE-M3 D+S RRF + Cross-Encoder",
      "precision_at_3": 0.94,
      "avg_top1_ontology": 0.8234,
      "avg_top1_legal": 0.7856,
      "latency_p95_ms": 285,
      "reranker_model": "dragonkue/bge-reranker-v2-m3-ko",
      "reranker_candidates": 50
    },
    "F": {
      "description": "v2 BGE-M3 D+S+ColBERT 3-Way RRF",
      "precision_at_3": 0.90,
      "avg_top1_ontology": 0.0312,
      "avg_top1_legal": 0.0298,
      "latency_p95_ms": 55
    }
  }
}
```

> **참고**: 설정 E의 Top-1 Score(예시 0.8234)가 설정 C(0.7907)보다 높은 이유는 Cross-Encoder의 sigmoid 스코어가 RRF 스코어와 다른 스케일이기 때문이다. 절대값 비교가 아닌 **순위 변화(P@3)**로 성능을 판단해야 한다.

---

## 6. Qdrant Payload 설정

Cross-Encoder가 문서 텍스트를 읽어야 하므로, Qdrant에 색인할 때 `embedding_text` 필드를 payload에 포함해야 한다.

### 현재 `index_phase2_v2.py`의 payload 구조 확인

```python
# index_phase2_v2.py에서 PointStruct 생성 시:
payload = {
    "term": entry["term"],
    "branch": branch,
    "category_path": entry.get("category_path", ""),
    "aliases": entry.get("aliases", []),
    # ... 기타 메타데이터 ...
}
```

### 수정: `embedding_text` 필드 추가

```python
# _build_ontology_text() 결과를 payload에도 저장
text = _build_ontology_text(entry, prefix)
payload = {
    "term": entry["term"],
    "branch": branch,
    "category_path": entry.get("category_path", ""),
    "aliases": entry.get("aliases", []),
    "embedding_text": text,   # ← Cross-Encoder 리랭킹용
}
```

> **주의**: `embedding_text`를 payload에 저장하면 Qdrant의 스토리지 사용량이 증가한다. 온톨로지 2,146건의 텍스트(평균 200자 × 2,146 = ~430KB)이므로 무시할 수 있는 수준이다.

---

## 7. 의존성 및 설치

### 필요 라이브러리

```bash
# FlagEmbedding이 이미 설치되어 있으므로 추가 설치 불필요
# bge-reranker-v2-m3-ko 모델은 첫 실행 시 자동 다운로드 (~1.1GB)
pip install FlagEmbedding  # 이미 설치됨 (embedder_bgem3.py에서 사용 중)
```

### GPU 메모리 예산

| 모델 | FP16 메모리 | 용도 |
|------|-----------|------|
| BGE-M3 (BGEM3FlagModel) | ~3GB | 임베딩 (Dense+Sparse+ColBERT) |
| bge-reranker-v2-m3-ko (FlagReranker) | ~2GB | 리랭킹 |
| **합계** | **~5GB** | 동시 로드 |
| DGX Spark 가용 GPU 메모리 | 128GB | — |

> **쉬운 비유 — GPU 메모리:**
>
> GPU 메모리를 "작업 책상"이라고 하면, DGX Spark의 책상은 **128GB** 크기이다. BGE-M3가 교과서(3GB)를, Reranker가 참고서(2GB)를 올려놓아도 책상의 4%만 사용한다. 공간은 넉넉하다.
