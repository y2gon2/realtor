# `codes/query/pipeline.py` — SearchPipeline 상세 코드 설계

> 목적: QueryAnalyzer의 분석 결과를 받아 기존 검색 함수로 검색을 실행하고, 결과를 병합하는 오케스트레이터
> 패턴 원본: `codes/embedding/search_test_phase2_v2.py` (검색 함수 재사용)
> 선행 문서: `02_query_analyzer_design.md`

---

## 1. 전체 구조

### 1-1. 파이프라인 흐름도

```
SearchPipeline.search(query)
    │
    ├── [1] analyzer.analyze(query)
    │       → QueryAnalysis (type, queries, ...)
    │
    ├── [2] 각 sub_query에 대해:
    │       embed_query(sub_q.query)
    │           → (dense, sparse, colbert)
    │
    ├── [3] 각 sub_query에 대해:
    │       search_ontology(...)  → onto_results
    │       search_legal(...)     → legal_results
    │
    ├── [4] type == DECOMPOSE이면:
    │       rrf_merge(all_onto_results) → merged_onto
    │       rrf_merge(all_legal_results) → merged_legal
    │
    └── [5] PipelineResult 반환
```

> **쉬운 비유 — 식당 주방의 주문 처리:**
>
> SearchPipeline은 **주방장**(오케스트레이터)이다. 손님(사용자)의 주문이 들어오면:
> 1. **통역사**(QueryAnalyzer)가 주문을 정리한다 ("그거 좀 주세요" → "된장찌개 1인분")
> 2. **재료 준비**(embed_query)를 한다 (각 요리에 필요한 재료를 꺼냄)
> 3. **요리사들**(search_ontology, search_legal)이 각자 담당 음식을 만든다
> 4. **합상**(rrf_merge)하여 한 상에 올린다 (여러 요리를 하나의 식탁에)
> 5. **서빙**(PipelineResult)한다

### 1-2. 모듈 의존 관계

```
pipeline.py
    ├── analyzer.py              → QueryAnalyzer (질의 분석)
    ├── merger.py                → rrf_merge() (결과 병합)
    ├── embedder_bgem3.py        → embed_query() (임베딩)
    └── search_test_phase2_v2.py → search_ontology(), search_legal() (검색)
```

---

## 2. `merger.py` — RRF 결과 병합

### 2-1. RRF(Reciprocal Rank Fusion)란?

> **쉬운 비유 — 위원회 투표:**
>
> 3명의 심사위원이 각자 후보자 명단을 순위별로 제출했다고 하자.
>
> - A 심사위원: 김○○(1위), 이○○(2위), 박○○(3위)
> - B 심사위원: 이○○(1위), 박○○(2위), 최○○(3위)
> - C 심사위원: 박○○(1위), 김○○(2위), 이○○(3위)
>
> RRF는 각 후보자가 받은 순위를 **역수(reciprocal)**로 변환하여 합산한다:
>
> - 김○○: 1/(60+1) + 1/(60+2) = 0.0164 + 0.0161 = 0.0325
> - 이○○: 1/(60+2) + 1/(60+1) + 1/(60+3) = 0.0161 + 0.0164 + 0.0159 = 0.0484
> - 박○○: 1/(60+3) + 1/(60+2) + 1/(60+1) = 0.0159 + 0.0161 + 0.0164 = 0.0484
> - 최○○: 1/(60+3) = 0.0159
>
> 여기서 60은 **k 파라미터**로, 순위 간 점수 차이를 조절한다. k가 클수록 상위권과 하위권의 점수 차이가 줄어든다.
>
> 이미 Qdrant 내부에서 Dense+Sparse를 RRF로 합산하고 있다 (Setting C). 이번에는 **서브 질의 간의 결과를 RRF로 합산**하는 것이다.

### 2-2. 코드

```python
#!/usr/bin/env python3
"""
결과 병합 모듈 — DECOMPOSE 질의의 서브 질의별 검색 결과를 RRF로 합산.

Qdrant 내부에서도 Dense+Sparse를 RRF로 합산하지만(1차 퓨전),
여기서는 서브 질의 간의 결과를 합산하는 2차 퓨전이다.

사용 예시:
    from merger import rrf_merge
    merged = rrf_merge([onto_results_q1, onto_results_q2])
"""

from __future__ import annotations


def rrf_merge(
    result_lists: list[list],
    k: int = 60,
    weights: list[float] | None = None,
) -> list:
    """N개의 검색 결과 리스트를 RRF(Reciprocal Rank Fusion)로 합산.

    Args:
        result_lists: 서브 질의별 Qdrant 검색 결과 리스트들.
                      각 내부 리스트는 ScoredPoint 객체의 리스트.
        k: RRF 파라미터. 순위 간 점수 차이를 조절한다.
           기본값 60은 원 논문의 권장값이다.
        weights: 각 결과 리스트의 가중치. None이면 자동 설정:
                 첫 번째 리스트 1.0, 이후 0.7.

    Returns:
        RRF 점수 기준 내림차순 정렬된 결과 리스트.
        point.id 기준 중복 제거됨.

    예시:
        # 서브 질의 2개의 결과를 합산
        merged = rrf_merge([
            ontology_hits_from_query1,  # "경매 낙찰 절차" 검색 결과
            ontology_hits_from_query2,  # "취득세 세율" 검색 결과
        ])
    """
    if not result_lists:
        return []

    if len(result_lists) == 1:
        return result_lists[0]

    # 가중치 기본값: 첫 번째(주 의도) 1.0, 나머지 0.7
    if weights is None:
        weights = [1.0] + [0.7] * (len(result_lists) - 1)

    # RRF 점수 계산
    scores: dict[str, float] = {}       # point_id → 누적 RRF 점수
    points: dict[str, object] = {}      # point_id → point 객체 (첫 등장 것 보존)

    for weight, result_list in zip(weights, result_lists):
        for rank, point in enumerate(result_list):
            pid = str(point.id)

            # RRF 공식: weight × 1 / (k + rank + 1)
            rrf_score = weight * (1.0 / (k + rank + 1))
            scores[pid] = scores.get(pid, 0.0) + rrf_score

            # 중복 제거: 첫 등장한 point 객체를 보존
            if pid not in points:
                points[pid] = point

    # 점수 기준 내림차순 정렬
    sorted_ids = sorted(scores, key=lambda pid: scores[pid], reverse=True)
    return [points[pid] for pid in sorted_ids]
```

### 2-3. 가중치 설계 근거

> **왜 첫 번째 서브 질의에 더 높은 가중치를 주는가?**
>
> "경매 낙찰되면 세금 내야해?"라는 질의에서 LLM은 다음과 같이 분해한다:
> 1. "부동산 경매 낙찰 절차와 낙찰자 의무" (경매 — 주 의도)
> 2. "경매 낙찰 부동산 취득세 세율" (세금 — 부 의도)
>
> LLM이 출력하는 `queries` 배열의 **첫 번째 항목이 사용자의 주된 관심사**에 해당한다. 프롬프트에서 이 순서를 의도적으로 유도한다.
>
> 가중치 1.0 vs 0.7은 실험적으로 조정할 수 있다. 너무 큰 차이(1.0 vs 0.3)를 주면 부 의도의 결과가 거의 반영되지 않고, 동일 가중치(1.0 vs 1.0)를 주면 부 의도가 주 의도를 압도할 수 있다.

---

## 3. `pipeline.py` — SearchPipeline 오케스트레이터

### 3-1. 데이터 클래스

```python
#!/usr/bin/env python3
"""
SearchPipeline — Query Decomposition 통합 검색 파이프라인.

QueryAnalyzer → BGE-M3 임베딩 → Qdrant 검색 → 결과 병합을 오케스트레이션한다.
기존 search_test_phase2_v2.py의 검색 함수를 그대로 재사용한다.

사용 예시:
    pipeline = SearchPipeline()
    result = pipeline.search("경매 낙찰되면 세금 내야해?")
    for point in result.ontology_results:
        print(point.payload["term"])
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from qdrant_client import QdrantClient

# 기존 모듈 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embedding"))
from embedder_bgem3 import embed_query
from search_test_phase2_v2 import search_ontology, search_legal

# 신규 모듈 import
from analyzer import QueryAnalyzer, QueryAnalysis
from merger import rrf_merge


# ─────────────────────────── 데이터 클래스 ───────────────────

@dataclass
class PipelineResult:
    """검색 파이프라인 전체 결과."""
    ontology_results: list          # 온톨로지 검색 결과 (ScoredPoint 리스트)
    legal_results: list             # 법률 검색 결과 (ScoredPoint 리스트)
    analysis: QueryAnalysis         # 질의 분석 결과 (type, queries, ...)
    total_latency_ms: float = 0.0   # 전체 파이프라인 소요 시간 (ms)
    search_count: int = 0           # 실행된 검색 횟수
```

### 3-2. SearchPipeline 클래스

```python
# ─────────────────── SearchPipeline ───────────────────────────

# 컬렉션명 상수
ONTOLOGY_COLLECTION = "domain_ontology_v2"
LEGAL_COLLECTION = "legal_docs_v2"

# 검색 모드 (Setting C 사용)
SEARCH_MODE = "hybrid_rrf"


class SearchPipeline:
    """Query Decomposition 통합 검색 파이프라인.

    전체 흐름:
      1. QueryAnalyzer로 질의 분석 (SIMPLE/REWRITE/DECOMPOSE)
      2. 분석 결과의 각 서브 질의를 BGE-M3로 임베딩
      3. 각 서브 질의로 Qdrant 검색 (기존 search_ontology/search_legal 재사용)
      4. DECOMPOSE인 경우 서브 질의별 결과를 RRF로 병합
    """

    def __init__(
        self,
        qdrant_url: str = "http://qdrant:6333",
        model: str = "claude-sonnet-4-6",
    ):
        """
        Args:
            qdrant_url: Qdrant 서버 URL
            model: QueryAnalyzer용 Claude 모델명
        """
        self.qdrant = QdrantClient(url=qdrant_url, timeout=60)
        self.analyzer = QueryAnalyzer(model=model)
        print(f"[SearchPipeline] 초기화 완료 (Qdrant: {qdrant_url})")

    def search(
        self,
        query: str,
        limit: int = 5,
        search_ontology_only: bool = False,
        search_legal_only: bool = False,
    ) -> PipelineResult:
        """질의 분석 → 임베딩 → 검색 → 병합의 전체 파이프라인을 실행.

        Args:
            query: 사용자 입력 질의
            limit: 최종 반환할 결과 수
            search_ontology_only: True면 온톨로지만 검색
            search_legal_only: True면 법률문서만 검색

        Returns:
            PipelineResult: 온톨로지 결과, 법률 결과, 분석 결과 포함
        """
        t0 = time.time()

        # ── Step 1: 질의 분석 ──────────────────────────────────
        analysis = self.analyzer.analyze(query)

        # ── Step 2-3: 각 서브 질의에 대해 임베딩 + 검색 ─────────
        all_onto_results = []
        all_legal_results = []
        search_count = 0

        # DECOMPOSE 시 over-fetch (병합 후 cut하므로)
        fetch_limit = limit * 2 if analysis.type == "DECOMPOSE" else limit

        for sub_q in analysis.queries:
            # 임베딩
            dense, sparse, colbert = embed_query(sub_q.query)

            # 온톨로지 검색
            if not search_legal_only:
                onto_hits = search_ontology(
                    self.qdrant,
                    ONTOLOGY_COLLECTION,
                    dense, sparse, colbert,
                    mode=SEARCH_MODE,
                    limit=fetch_limit,
                )
                all_onto_results.append(onto_hits)
                search_count += 1

            # 법률문서 검색
            if not search_ontology_only:
                legal_hits = search_legal(
                    self.qdrant,
                    LEGAL_COLLECTION,
                    dense, sparse, colbert,
                    mode=SEARCH_MODE,
                    limit=fetch_limit,
                )
                all_legal_results.append(legal_hits)
                search_count += 1

        # ── Step 4: 결과 병합 (DECOMPOSE만) ────────────────────
        if analysis.type == "DECOMPOSE" and len(analysis.queries) > 1:
            # 서브 질의 결과들을 RRF로 합산
            if all_onto_results:
                onto_final = rrf_merge(all_onto_results)[:limit]
            else:
                onto_final = []

            if all_legal_results:
                legal_final = rrf_merge(all_legal_results)[:limit]
            else:
                legal_final = []
        else:
            # SIMPLE/REWRITE: 단일 결과만 사용
            onto_final = all_onto_results[0][:limit] if all_onto_results else []
            legal_final = all_legal_results[0][:limit] if all_legal_results else []

        total_latency = (time.time() - t0) * 1000

        return PipelineResult(
            ontology_results=onto_final,
            legal_results=legal_final,
            analysis=analysis,
            total_latency_ms=total_latency,
            search_count=search_count,
        )
```

> **코드 해설 — over-fetch란?**
>
> DECOMPOSE 질의에서는 2~3개 서브 질의의 결과를 합산하므로, 각 서브 질의에서 더 많은 결과(limit × 2)를 가져온다. 합산 후 상위 limit개만 잘라낸다. 예를 들어 limit=5이면 각 서브 질의에서 10개씩 가져와서 RRF로 합산한 뒤 상위 5개를 반환한다. 이를 "over-fetch"라고 한다.
>
> SIMPLE/REWRITE에서는 단일 질의이므로 over-fetch가 불필요하다.

---

## 4. 단독 실행 (CLI)

```python
# ─────────────────── CLI: 파이프라인 테스트 ────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query Decomposition 통합 검색")
    parser.add_argument("query", nargs="?", default=None,
                       help="검색할 질의 (없으면 샘플 10개 실행)")
    parser.add_argument("--qdrant-url", default="http://qdrant:6333",
                       help="Qdrant 서버 URL")
    parser.add_argument("--limit", type=int, default=5,
                       help="반환할 결과 수")
    args = parser.parse_args()

    pipeline = SearchPipeline(qdrant_url=args.qdrant_url)

    if args.query:
        # 단일 질의 검색
        result = pipeline.search(args.query, limit=args.limit)
        _print_result(result)
    else:
        # 샘플 질의 검색
        sample_queries = [
            "종부세 기준 금액",
            "부동산 사면 나라에 돈 내야 되나",
            "은행에서 집값의 몇 프로까지 빌려주는지",
            "경매 낙찰되면 세금 내야해?",
            "집 살 때 세금 얼마야",
        ]

        for q in sample_queries:
            result = pipeline.search(q, limit=args.limit)
            _print_result(result)


def _print_result(result: PipelineResult) -> None:
    """검색 결과를 포맷팅하여 출력."""
    a = result.analysis
    print(f"\n{'='*70}")
    print(f"질의: {a.original_query}")
    print(f"유형: {a.type} | LLM: {'O' if a.llm_called else 'X'} | "
          f"검색 {result.search_count}회 | 총 {result.total_latency_ms:.0f}ms")
    print(f"근거: {a.reasoning}")

    if len(a.queries) > 1:
        print(f"서브 질의:")
        for i, sq in enumerate(a.queries):
            print(f"  [{i+1}] {sq.query} ({sq.domain_hint})")

    print(f"\n--- 온톨로지 결과 (Top-{len(result.ontology_results)}) ---")
    for i, point in enumerate(result.ontology_results):
        term = point.payload.get("term", "?")
        score = point.score if hasattr(point, 'score') and point.score else 0
        branch = point.payload.get("branch", "?")
        print(f"  [{i+1}] {score:.4f} | {term} ({branch})")

    print(f"\n--- 법률 결과 (Top-{len(result.legal_results)}) ---")
    for i, point in enumerate(result.legal_results[:3]):
        section = (point.payload.get("section_title", "") or
                   point.payload.get("part_title", ""))
        score = point.score if hasattr(point, 'score') and point.score else 0
        print(f"  [{i+1}] {score:.4f} | {section}")
```

---

## 5. 향후 확장: Cross-Encoder 통합 (P1-b)

P1-b에서 `reranker.py`를 파이프라인에 선택적으로 통합할 수 있다.

> **쉬운 비유 — 2차 심사 추가:**
>
> 현재 파이프라인은 "1차 서류 심사"(RRF)로 최종 결과를 결정한다. P1-b에서는 서류 심사로 50명을 뽑은 후, **면접(Cross-Encoder)**으로 최종 5명을 선정하는 단계를 추가한다. Query Rewriting으로 서류의 품질(후보 풀)이 개선되면, 면접관의 정밀한 판단이 더 효과적으로 작동한다.

```python
# P1-b 확장 시 pipeline.py에 추가할 코드 (현 단계에서는 미구현)

from reranker import rerank_results

class SearchPipeline:
    def search(self, query, limit=5, use_reranker=False):
        # ... 기존 코드 ...

        if use_reranker and onto_final:
            # RRF 결과를 Cross-Encoder로 리랭킹
            # reranker.py의 rerank_results()를 호출
            reranked = rerank_results(
                query=query,
                points=onto_final,  # 또는 over-fetch된 더 많은 후보
                top_k=limit,
            )
            # RerankItem → ScoredPoint 호환 변환
            onto_final = [_PointLike(r) for r in reranked]
```

이미 구현된 `reranker.py`와 `benchmark_phase2_v2.py`의 `_PointLike` 패턴을 그대로 재사용한다.

---

## 6. 실행 방법

### 6-1. Docker 컨테이너 내에서 실행

```bash
# rag-embedding 컨테이너 접속
docker exec -it rag-embedding bash

# 단일 질의 테스트
python3 codes/query/pipeline.py "부동산 사면 나라에 돈 내야 되나"

# 샘플 10개 테스트
python3 codes/query/pipeline.py

# Qdrant URL 변경 (호스트에서 직접 실행 시)
python3 codes/query/pipeline.py --qdrant-url http://localhost:6333 "경매 낙찰되면 세금 내야해?"
```

### 6-2. 환경 변수 설정

```bash
# Claude API 키 (필수 — QueryAnalyzer에서 사용)
export ANTHROPIC_API_KEY="sk-ant-..."

# 또는 .env 파일에 설정 (기존 인프라)
echo "ANTHROPIC_API_KEY=sk-ant-..." >> /home/gon/ws/rag/.env
```
