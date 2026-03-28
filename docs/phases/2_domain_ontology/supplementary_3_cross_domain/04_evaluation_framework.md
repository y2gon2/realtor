# 평가 프레임워크 — `test_query_decomposition.py` 설계

> 목적: Query Decomposition 파이프라인의 성능을 정량 평가하고, 기존 Setting C 대비 개선 효과를 검증
> 패턴 원본: `codes/embedding/search_test_phase2_v2.py` (질의 세트, expected dict, Precision@3 계산)
> 선행 문서: `01_query_decomposition_plan.md` §6, `03_search_pipeline_design.md`

---

## 1. 평가 전략 개요

### 1-1. 왜 체계적인 평가가 필요한가?

> **쉬운 비유 — 약효 검증:**
>
> 새로운 약이 개발되면, "환자 1명에게 줬더니 낫더라"로는 약효를 증명할 수 없다. **대조군**(기존 약)과 **실험군**(새 약)을 비교하고, 충분한 수의 환자에게 테스트하고, 기존에 잘 치료되던 질병이 악화되지 않았는지(회귀) 확인해야 한다.
>
> 검색 시스템도 마찬가지다:
> - **대조군** = Setting C (현재 운영, LLM 없음)
> - **실험군** = Query Decomposition 파이프라인 (LLM 포함)
> - **회귀 테스트** = 기존에 성공하던 질의가 여전히 성공하는지

### 1-2. 3가지 비교 설정

| 설정 | 설명 | 파이프라인 |
|------|------|----------|
| **Baseline** | Setting C (현재 운영) | Query → Embed → Qdrant D+S RRF |
| **Rewrite-only** | LLM 변환만, 분해 없음 | Query → LLM(REWRITE) → Embed → Qdrant D+S RRF |
| **Full Pipeline** | LLM 변환 + 분해 + 병합 | Query → LLM(ALL) → Embed → Qdrant D+S RRF → RRF merge |

> **왜 Rewrite-only를 별도로 테스트하는가?**
>
> 개선 효과의 원인을 분리하기 위해서다. "Query Rewriting만으로 2개 실패 질의가 해결되는가?"와 "DECOMPOSE가 Cross-domain 질의에서 추가 효과가 있는가?"를 별개로 확인할 수 있다. 이를 **ablation study**(제거 실험)라고 한다.

> **Ablation Study란?**
>
> 시스템의 각 구성 요소를 하나씩 제거하면서 성능 변화를 측정하는 실험 방법이다. "이 부품이 없으면 성능이 얼마나 떨어지는가?"를 확인하여 각 부품의 기여도를 정량화한다.
>
> - Full에서 DECOMPOSE를 제거 → Rewrite-only → DECOMPOSE의 기여도
> - Rewrite-only에서 LLM을 제거 → Baseline → Rewriting의 기여도

---

## 2. 테스트 질의 세트 (4종)

### 2-1. Set A: 기존 25개 온톨로지 질의 (회귀 테스트)

`search_test_phase2_v2.py`의 기존 질의와 `expected` dict를 그대로 import하여 사용한다.

```python
# search_test_phase2_v2.py에서 import
from search_test_phase2_v2 import (
    ontology_queries,          # 25개 질의 리스트
    expected,                  # 질의별 기대 키워드 dict
)
```

**목적**: 기존 92% P@3를 유지하는지 확인 (회귀 없음 검증)

### 2-2. Set B: 2개 기존 실패 질의 (핵심 타겟)

```python
failure_queries = {
    "부동산 사면 나라에 돈 내야 되나": {
        "expected_keywords": ["취득세", "세금", "과세"],
        "failure_reason": "극단적 구어체 — '나라에 돈' ↔ '취득세' 의미 격차",
        "expected_type": "REWRITE",
    },
    "은행에서 집값의 몇 프로까지 빌려주는지": {
        "expected_keywords": ["LTV", "담보", "대출"],
        "failure_reason": "개념 격차 — '빌려주는' ↔ 'LTV' 연결 실패",
        "expected_type": "REWRITE",
    },
}
```

**목적**: 이 2개 질의가 Query Rewriting으로 **반드시** 해결되는지 확인. P1-a의 핵심 성공 기준.

### 2-3. Set C: 10개 신규 Cross-Domain 질의

```python
cross_domain_queries = {
    # ─── 경매 + 세금 ───
    "경매 낙찰되면 세금 내야해?": {
        "expected_keywords": ["경매", "낙찰", "취득세"],
        "domains": ["auction", "tax"],
        "expected_type": "DECOMPOSE",
    },
    "공매로 집 사면 세금 얼마야": {
        "expected_keywords": ["공매", "취득세"],
        "domains": ["auction", "tax"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 재건축 + 세금 ───
    "재건축 아파트 팔 때 양도세 얼마": {
        "expected_keywords": ["재건축", "양도소득세"],
        "domains": ["reconstruction", "tax"],
        "expected_type": "DECOMPOSE",
    },
    "재개발 조합원 분양 취득세": {
        "expected_keywords": ["재개발", "조합원", "취득세"],
        "domains": ["reconstruction", "tax"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 임대 + 세금 ───
    "전세 놓으면 세금 내야 하나": {
        "expected_keywords": ["임대소득세", "전세", "임대"],
        "domains": ["rental", "tax"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 청약 + 대출 ───
    "청약 당첨되면 대출 얼마까지 받을 수 있어": {
        "expected_keywords": ["청약", "대출", "LTV"],
        "domains": ["subscription", "loan"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 계약 + 등기 ───
    "집 계약하고 등기 언제 해야 돼": {
        "expected_keywords": ["매매계약", "소유권이전등기", "등기"],
        "domains": ["contract", "registration"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 경매 + 대출 ───
    "경매 집 대출 가능해?": {
        "expected_keywords": ["경매", "담보대출", "대출"],
        "domains": ["auction", "loan"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 규제 + 세금 ───
    "조정대상지역 집 사면 세금 더 내?": {
        "expected_keywords": ["조정대상지역", "취득세", "중과"],
        "domains": ["regulation", "tax"],
        "expected_type": "DECOMPOSE",
    },

    # ─── 토지 + 규제 ───
    "농지 전용하려면 허가 받아야 해?": {
        "expected_keywords": ["농지전용", "개발행위허가", "허가"],
        "domains": ["land", "regulation"],
        "expected_type": "DECOMPOSE",
    },
}
```

**목적**: Cross-domain 질의에서 DECOMPOSE가 효과적인지 검증. 각 도메인의 결과가 모두 Top-K에 포함되는지 확인.

### 2-4. Set D: 5개 극단적 구어체 질의

```python
extreme_colloquial_queries = {
    "집 두 채인데 하나 팔면 얼마나 떼가": {
        "expected_keywords": ["양도소득세", "다주택", "중과"],
        "expected_type": "REWRITE",
    },
    "아파트 보증금 돌려받는 방법 알려줘": {
        "expected_keywords": ["보증금", "반환", "임대차보호"],
        "expected_type": "REWRITE",
    },
    "빚 내서 집 사면 이자 얼마나 나와": {
        "expected_keywords": ["대출이자", "주택담보", "금리"],
        "expected_type": "REWRITE",
    },
    "세입자가 안 나가면 어쩌지": {
        "expected_keywords": ["명도", "임차권", "퇴거"],
        "expected_type": "REWRITE",
    },
    "세금 한꺼번에 못 내면 어떡해": {
        "expected_keywords": ["분할납부", "징수유예", "납부"],
        "expected_type": "REWRITE",
    },
}
```

**목적**: Query Rewriting이 다양한 구어체 표현을 처리할 수 있는지 검증.

---

## 3. 평가 지표

### 3-1. 검색 품질 지표

| 지표 | 정의 | 산식 | 목표 |
|------|------|------|------|
| **Precision@3** | Top-3 결과 중 기대 키워드를 포함하는 결과가 1개 이상인 질의의 비율 | 성공 질의 수 / 전체 질의 수 | Set A ≥ 92%, Set B = 100% |
| **Cross-domain Coverage** | DECOMPOSE 질의에서 기대된 모든 도메인이 Top-K에 포함된 비율 | 커버된 도메인 수 / 기대 도메인 수 | ≥ 80% |

> **Precision@3이란?**
>
> "상위 3개 검색 결과 중에서 정답이 하나라도 있는가?"를 측정하는 지표이다. 예를 들어 "집 살 때 세금 얼마야"라는 질의에 대해 Top-3에 "취득세"가 포함되어 있으면 성공(O), 포함되어 있지 않으면 실패(X)이다.
>
> 우리 프로젝트에서는 `search_test_phase2_v2.py`의 `check_precision()` 함수와 동일한 로직을 사용한다:
>
> ```python
> def check_precision(query, top3_terms):
>     exp_keywords = expected.get(query, [])
>     return any(
>         any(kw in term for kw in exp_keywords)
>         for term in top3_terms
>     )
> ```

### 3-2. 시스템 지표

| 지표 | 정의 | 목표 |
|------|------|------|
| **LLM 호출율** | LLM을 호출한 질의 비율 | ≤ 60% |
| **E2E Latency p95** | 전체 파이프라인 95번째 백분위수 응답 시간 | < 800ms |
| **분석 정확도** | LLM이 올바른 type을 판정한 비율 | ≥ 90% |

---

## 4. 벤치마크 스크립트

### 4-1. 전체 구조

```python
#!/usr/bin/env python3
"""
test_query_decomposition.py — Query Decomposition 평가 하니스.

3가지 설정(Baseline / Rewrite-only / Full Pipeline)을 4개 테스트 세트(A~D)에 대해
벤치마크하고, 설정 간 비교 리포트를 생성한다.

사용법:
    # 전체 벤치마크 (3설정 × 4세트)
    python3 codes/query/test_query_decomposition.py

    # 특정 설정만
    python3 codes/query/test_query_decomposition.py --setting full

    # 특정 세트만
    python3 codes/query/test_query_decomposition.py --set B

    # JSON 리포트 저장
    python3 codes/query/test_query_decomposition.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from qdrant_client import QdrantClient

# 기존 모듈
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embedding"))
from embedder_bgem3 import embed_query, to_qdrant_sparse
from search_test_phase2_v2 import (
    ontology_queries, expected, check_precision,
    search_ontology, search_legal,
)

# 신규 모듈
from pipeline import SearchPipeline, PipelineResult


# ─────────────── 테스트 세트 정의 ──────────────────────────────

# Set A: 기존 25개 (search_test_phase2_v2.py에서 import)
SET_A_QUERIES = ontology_queries

# Set B: 2개 실패 질의
SET_B_QUERIES = [
    "부동산 사면 나라에 돈 내야 되나",
    "은행에서 집값의 몇 프로까지 빌려주는지",
]

# Set C: 10개 Cross-Domain
SET_C_QUERIES = [
    "경매 낙찰되면 세금 내야해?",
    "공매로 집 사면 세금 얼마야",
    "재건축 아파트 팔 때 양도세 얼마",
    "재개발 조합원 분양 취득세",
    "전세 놓으면 세금 내야 하나",
    "청약 당첨되면 대출 얼마까지 받을 수 있어",
    "집 계약하고 등기 언제 해야 돼",
    "경매 집 대출 가능해?",
    "조정대상지역 집 사면 세금 더 내?",
    "농지 전용하려면 허가 받아야 해?",
]

# Set D: 5개 극단적 구어체
SET_D_QUERIES = [
    "집 두 채인데 하나 팔면 얼마나 떼가",
    "아파트 보증금 돌려받는 방법 알려줘",
    "빚 내서 집 사면 이자 얼마나 나와",
    "세입자가 안 나가면 어쩌지",
    "세금 한꺼번에 못 내면 어떡해",
]

# Set C, D의 기대 키워드 (expected dict에 추가)
EXTENDED_EXPECTED = {
    # Set C
    "경매 낙찰되면 세금 내야해?": ["경매", "낙찰", "취득세", "세금"],
    "공매로 집 사면 세금 얼마야": ["공매", "취득세", "세금"],
    "재건축 아파트 팔 때 양도세 얼마": ["재건축", "양도", "소득세"],
    "재개발 조합원 분양 취득세": ["재개발", "조합원", "취득세"],
    "전세 놓으면 세금 내야 하나": ["임대", "소득세", "전세", "세금"],
    "청약 당첨되면 대출 얼마까지 받을 수 있어": ["청약", "대출", "LTV", "한도"],
    "집 계약하고 등기 언제 해야 돼": ["계약", "등기", "이전", "소유권"],
    "경매 집 대출 가능해?": ["경매", "대출", "담보"],
    "조정대상지역 집 사면 세금 더 내?": ["조정", "취득세", "중과", "세금"],
    "농지 전용하려면 허가 받아야 해?": ["농지", "전용", "허가", "개발"],
    # Set D
    "집 두 채인데 하나 팔면 얼마나 떼가": ["양도", "소득세", "다주택", "중과"],
    "아파트 보증금 돌려받는 방법 알려줘": ["보증금", "반환", "보호", "임대"],
    "빚 내서 집 사면 이자 얼마나 나와": ["대출", "이자", "담보", "금리"],
    "세입자가 안 나가면 어쩌지": ["명도", "임차", "퇴거", "갱신"],
    "세금 한꺼번에 못 내면 어떡해": ["분할", "납부", "징수", "유예"],
}

# 전체 기대 키워드 병합
ALL_EXPECTED = {**expected, **EXTENDED_EXPECTED}
```

### 4-2. 검색 함수 (설정별)

```python
# ─────────────── 설정별 검색 함수 ──────────────────────────────

def search_baseline(
    client: QdrantClient, query: str, limit: int = 5
) -> list:
    """Baseline (Setting C): 기존 hybrid_rrf 검색. LLM 호출 없음."""
    dense, sparse, colbert = embed_query(query)
    return search_ontology(
        client, "domain_ontology_v2",
        dense, sparse, colbert,
        mode="hybrid_rrf",
        limit=limit,
    )


def search_with_pipeline(
    pipeline: SearchPipeline, query: str, limit: int = 5
) -> tuple[list, dict]:
    """Full Pipeline: Query Decomposition 파이프라인으로 검색.

    Returns:
        (ontology_results, metadata_dict)
    """
    result = pipeline.search(query, limit=limit, search_ontology_only=True)
    metadata = {
        "type": result.analysis.type,
        "reasoning": result.analysis.reasoning,
        "llm_called": result.analysis.llm_called,
        "sub_queries": [sq.query for sq in result.analysis.queries],
        "latency_ms": result.total_latency_ms,
    }
    return result.ontology_results, metadata
```

### 4-3. 메인 벤치마크 루프

```python
# ─────────────── 벤치마크 실행 ─────────────────────────────────

@dataclass
class QueryResult:
    """질의 하나의 벤치마크 결과."""
    query: str
    setting: str               # "baseline" | "full"
    top3_terms: list[str]
    top1_score: float
    top1_term: str
    precision_ok: bool         # P@3 성공 여부
    latency_ms: float
    metadata: dict = field(default_factory=dict)


def run_benchmark(
    client: QdrantClient,
    pipeline: SearchPipeline,
    queries: list[str],
    set_name: str,
    limit: int = 5,
) -> dict:
    """하나의 테스트 세트에 대해 Baseline vs Full 벤치마크 실행.

    Returns:
        {
            "set_name": "A",
            "baseline": {"precision_at_3": 0.92, "results": [...]},
            "full":     {"precision_at_3": 0.96, "results": [...]},
        }
    """
    report = {"set_name": set_name}

    for setting in ["baseline", "full"]:
        results = []
        correct = 0

        print(f"\n--- Set {set_name} | {setting} ---")

        for query in queries:
            t0 = time.time()

            if setting == "baseline":
                hits = search_baseline(client, query, limit)
                metadata = {}
            else:
                hits, metadata = search_with_pipeline(pipeline, query, limit)

            latency = (time.time() - t0) * 1000

            top3_terms = [h.payload.get("term", "?") for h in hits[:3]]
            top1_score = hits[0].score if hits else 0
            top1_term = hits[0].payload.get("term", "?") if hits else "?"

            # P@3 판정
            exp_keywords = ALL_EXPECTED.get(query, [])
            ok = any(
                any(kw in term for kw in exp_keywords)
                for term in top3_terms
            ) if exp_keywords else True

            if ok:
                correct += 1

            status = "O" if ok else "X"
            qtype = metadata.get("type", "—")
            print(f"  [{status}] {qtype:10s} | {query}")
            print(f"       top1: {top1_score:.4f} | {top1_term} | top3: {top3_terms}")
            if metadata.get("sub_queries") and len(metadata["sub_queries"]) > 1:
                for sq in metadata["sub_queries"]:
                    print(f"       sub: {sq}")

            results.append(QueryResult(
                query=query,
                setting=setting,
                top3_terms=top3_terms,
                top1_score=top1_score,
                top1_term=top1_term,
                precision_ok=ok,
                latency_ms=latency,
                metadata=metadata,
            ))

        precision = correct / len(queries) * 100 if queries else 0
        avg_top1 = (sum(r.top1_score for r in results) / len(results)) if results else 0
        latencies = sorted(r.latency_ms for r in results)
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

        print(f"\n  P@3: {correct}/{len(queries)} = {precision:.0f}%")
        print(f"  Avg Top-1: {avg_top1:.4f}")
        print(f"  Latency p95: {p95:.0f}ms")

        report[setting] = {
            "precision_at_3": precision,
            "avg_top1": avg_top1,
            "latency_p95_ms": p95,
            "correct": correct,
            "total": len(queries),
            "results": [asdict(r) for r in results],
        }

    return report
```

### 4-4. 비교표 출력

```python
# ─────────────── 비교표 출력 ──────────────────────────────────

def print_comparison(reports: list[dict]) -> None:
    """전체 벤치마크 결과를 비교표로 출력."""

    print(f"\n{'='*80}")
    print("  QUERY DECOMPOSITION 벤치마크 비교표")
    print(f"{'='*80}")
    print(f"{'세트':<8} {'설정':<12} {'P@3':>8} {'Avg Top-1':>12} {'p95(ms)':>10} {'판정':>6}")
    print("-" * 60)

    for report in reports:
        set_name = report["set_name"]
        for setting in ["baseline", "full"]:
            data = report[setting]
            verdict = ""
            if setting == "full":
                base_p = report["baseline"]["precision_at_3"]
                full_p = data["precision_at_3"]
                if full_p > base_p:
                    verdict = "↑개선"
                elif full_p == base_p:
                    verdict = "=유지"
                else:
                    verdict = "↓하락"

            print(f"  {set_name:<6} {setting:<12} "
                  f"{data['precision_at_3']:>7.0f}% "
                  f"{data['avg_top1']:>12.4f} "
                  f"{data['latency_p95_ms']:>10.0f} "
                  f"{verdict:>6}")
        print()

    # 회귀 분석
    print("\n--- 회귀 분석 ---")
    set_a = next((r for r in reports if r["set_name"] == "A"), None)
    if set_a:
        base_results = {r["query"]: r for r in set_a["baseline"]["results"]}
        full_results = {r["query"]: r for r in set_a["full"]["results"]}

        regressions = []
        improvements = []

        for query in base_results:
            base_ok = base_results[query]["precision_ok"]
            full_ok = full_results.get(query, {}).get("precision_ok", False)

            if base_ok and not full_ok:
                regressions.append(query)
            elif not base_ok and full_ok:
                improvements.append(query)

        if regressions:
            print(f"  ⚠️ 회귀 {len(regressions)}건:")
            for q in regressions:
                print(f"    - {q}")
        else:
            print(f"  ✅ 회귀 없음 (기존 성공 질의 모두 유지)")

        if improvements:
            print(f"  ✨ 신규 해결 {len(improvements)}건:")
            for q in improvements:
                print(f"    - {q}")
```

### 4-5. CLI

```python
# ─────────────── CLI ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Query Decomposition 벤치마크"
    )
    parser.add_argument("--qdrant-url", default="http://qdrant:6333")
    parser.add_argument("--set", choices=["A", "B", "C", "D", "all"],
                       default="all", help="테스트 세트 (기본: all)")
    parser.add_argument("--output", type=str, default=None,
                       help="JSON 리포트 저장 경로")
    args = parser.parse_args()

    client = QdrantClient(url=args.qdrant_url, timeout=60)
    pipeline = SearchPipeline(qdrant_url=args.qdrant_url)

    # 테스트 세트 매핑
    set_map = {
        "A": ("A (기존 25개 회귀)", SET_A_QUERIES),
        "B": ("B (실패 질의 2개)", SET_B_QUERIES),
        "C": ("C (Cross-Domain 10개)", SET_C_QUERIES),
        "D": ("D (극단 구어체 5개)", SET_D_QUERIES),
    }

    sets_to_run = list(set_map.keys()) if args.set == "all" else [args.set]

    reports = []
    for set_key in sets_to_run:
        set_name, queries = set_map[set_key]
        report = run_benchmark(client, pipeline, queries, set_name)
        reports.append(report)

    # 비교표 출력
    print_comparison(reports)

    # LLM 호출율 계산
    all_full_results = []
    for r in reports:
        all_full_results.extend(r.get("full", {}).get("results", []))

    llm_count = sum(1 for r in all_full_results if r.get("metadata", {}).get("llm_called", False))
    total = len(all_full_results)
    if total:
        print(f"\n--- LLM 호출율 ---")
        print(f"  LLM 호출: {llm_count}/{total} ({llm_count/total*100:.0f}%)")
        print(f"  SKIP:    {total-llm_count}/{total} ({(total-llm_count)/total*100:.0f}%)")

    # JSON 리포트 저장
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(reports, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON 리포트 저장: {output_path}")


if __name__ == "__main__":
    main()
```

---

## 5. 성공 기준 종합

| 지표 | 기준 | Set | 의미 |
|------|------|-----|------|
| P@3 | ≥ 92% | A | 기존 성능 유지 (회귀 없음) |
| P@3 | 100% (2/2) | B | 2개 실패 질의 완전 해결 |
| P@3 | ≥ 80% | C | Cross-domain 커버리지 |
| P@3 | ≥ 60% | D | 극단 구어체 처리 능력 |
| LLM 호출율 | ≤ 60% | 전체 | 비용/레이턴시 효율 |
| E2E Latency p95 | < 800ms | 전체 | 서비스 수준 유지 |
| 회귀 건수 | 0건 | A | 기존 성공 질의 보존 |

### 의사결정 매트릭스

> **쉬운 비유 — 합격/불합격/보류:**
>
> 시험 결과에 따라 "합격"(채택), "불합격"(기각), "보류"(추가 조정 후 재시험)를 결정한다.

| 시나리오 | 조치 |
|---------|------|
| Set A ≥ 92% AND Set B = 100% | **채택** — 프로덕션 적용 |
| Set A ≥ 92% AND Set B < 100% | **보류** — 프롬프트 조정 후 재테스트 |
| Set A < 92% (회귀 발생) | **기각** — 회귀 원인 분석 후 사전 필터 조정 |

---

## 6. 결과 리포트 문서 구조

벤치마크 완료 후 다음 문서를 작성한다:

```
supplementary_3_cross_domain/
    ├── 01_query_decomposition_plan.md        # 이미 작성
    ├── 02_query_analyzer_design.md           # 이미 작성
    ├── 03_search_pipeline_design.md          # 이미 작성
    ├── 04_evaluation_framework.md            # 이 문서
    └── 05_benchmark_results.md               # 벤치마크 실행 후 작성 예정
```

`05_benchmark_results.md`에 포함될 내용:
- 설정 A~F + Query Decomposition 전체 비교표
- 질의별 상세 결과 (Baseline vs Full 비교)
- 회귀 분석
- LLM 분석 정확도 (분류 오류 사례)
- 레이턴시 프로파일링
- 최종 운영 설정 결정

---

## 7. 실행 방법

```bash
# Docker 컨테이너 내에서 실행
docker exec -it rag-embedding bash

# 환경 변수 설정
export ANTHROPIC_API_KEY="sk-ant-..."

# 전체 벤치마크 (Set A~D, Baseline vs Full)
python3 codes/query/test_query_decomposition.py

# Set B만 (실패 질의 2개 빠른 확인)
python3 codes/query/test_query_decomposition.py --set B

# JSON 리포트 저장
python3 codes/query/test_query_decomposition.py --output results/p1a_benchmark.json

# Qdrant URL 변경 (호스트에서 직접 실행 시)
python3 codes/query/test_query_decomposition.py --qdrant-url http://localhost:6333
```

---

## 8. 위험 요소 및 대응

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| Set A에서 회귀 발생 | 중 | P@3 하락 | 회귀 질의 분석 → 사전 필터 조건 강화 (해당 유형을 SIMPLE로 판정) |
| Set B 중 1개만 해결 | 중 | 핵심 목표 미달 | 해당 질의의 LLM 출력 수동 검토 → 프롬프트 few-shot 추가 |
| LLM 호출율 > 60% | 중 | 비용 초과 | 사전 필터 조건 완화 (정규 용어 매칭 기준 낮춤) |
| Cross-domain 결과가 한쪽 도메인에 치우침 | 중 | 커버리지 미달 | RRF 가중치 조정 (0.7 → 1.0 또는 도메인별 차등) |
| 벤치마크 실행 시 Rate Limit | 저 | 테스트 중단 | Set 단위로 나눠 실행, 재시도 로직 |
