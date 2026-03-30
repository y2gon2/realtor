# α 그리드 서치 + Query-type별 조건부 α

> 작성일: 2026-03-28
> 선행 문서: `01_phase2a_quickwins_plan.md`, `09_step5_rerank_results.md`
> 관련 코드: `codes/query/config.py`, `codes/query/pipeline.py`, `codes/query/test_query_decomposition.py`
> 목적: CE 점수 퓨전의 α를 질의 유형별로 최적화하여 P@3 +1-3%p 개선

---

## 1. 문제 정의

### 1-1. 현재 상태

현재 `pipeline.py:87`에서 α는 0.5로 고정:

```python
def _rerank_ontology(self, query, candidates, top_k=5, alpha=0.5):
    """final_score = alpha * rrf_rank_score + (1-alpha) * ce_score"""
```

이 고정값이 문제인 이유:

| 질의 유형 | 적합한 α | 이유 |
|----------|---------|------|
| 정규 질의 ("취득세 감면 대상") | **0.7** (CE 비중↑) | CE가 정규 질의-문서 쌍을 잘 판별 |
| 구어체 질의 ("나라에 돈 내야 되나") | **0.3** (CE 비중↓) | CE가 구어체를 이해하지 못해 오판 |
| REWRITE 질의 | **0.4** | 원본 질의의 RRF 결과가 보험 역할 |

> **비유**: 모든 과목의 시험을 객관식 50%, 서술식 50%로 채점하는 것과 같다. 수학은 객관식이 정확하고, 국어는 서술식이 정확한데, 일률적 비중은 두 과목 모두에서 최적이 아니다.

### 1-2. 연구 근거 — Convex Combination의 우위

**Bruch et al. (ACM TOIS 2023), "An Analysis of Fusion Functions for Hybrid Retrieval"**:

이 논문은 RRF와 Convex Combination(우리가 쓰는 방식)을 6개 데이터셋에서 비교했다:

```
방법              | 평균 nDCG@10 | 특징
─────────────────┼─────────────┼─────────────────────
RRF (k=60)       | 0.487       | 순위만 사용, α 불필요
Convex Comb.     | 0.513       | 점수 사용, α 튜닝 필요
Convex (α 최적화) | 0.531       | 도메인별 α 최적화
```

핵심 발견:
1. Convex Combination이 **모든 데이터셋에서** RRF 대비 우위
2. α 튜닝은 **10-50개 라벨 질의만으로** 도메인 최적값에 수렴
3. 최적 α는 **데이터셋마다 다름** (0.3 ~ 0.7)

→ 우리는 500개 라벨 질의를 보유하고 있으므로, 질의 유형별 α 최적화가 가능하고 신뢰도도 높다.

---

## 2. Step 1-A: 전역 α 그리드 서치

### 2-1. 개념

> **비유**: 오븐 온도를 맞추는 것. 150도~250도 사이에서 10도 간격으로 여러 번 구워보고, 가장 맛있는 온도를 찾는 것이 그리드 서치다.

α를 0.3부터 0.7까지 0.05 간격으로 9개 값을 테스트:

```
ALPHA_GRID = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
```

각 α 값에 대해 500개 질의 전체를 평가하고, 세트별 P@3을 기록한다.

### 2-2. 구현 코드

`codes/query/test_query_decomposition.py`에 추가된 함수:

```python
ALPHA_GRID = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]


def run_alpha_grid(
    client: QdrantClient,
    pipeline: SearchPipeline,
    set_map: dict,
    sets_to_run: list[str],
    output_path: str | None = None,
) -> dict:
    """α 값별 전체 P@3를 측정, 세트별 분리 리포트.

    각 α 값에 대해:
    1. 500개 질의를 full_rerank 모드로 실행
    2. 세트별 P@3 집계
    3. 전체 P@3 최대인 α를 최적값으로 선정

    LLM 호출 없이 CE rerank만 재실행하므로 GPU 연산만 필요.
    예상 소요: 500 × 9 = 4,500회 CE predict ≈ 2시간
    """
    results = {}

    for alpha in ALPHA_GRID:
        set_results = {}
        total_correct = 0
        total_queries = 0

        for key in sets_to_run:
            set_name, queries = set_map[key]
            correct = 0
            for query in queries:
                pr = pipeline.search(
                    query, limit=5, search_ontology_only=True,
                    rerank=True, rerank_candidates=20, rerank_alpha=alpha,
                )
                hits = pr.ontology_results
                top3 = [h.payload.get("term", "?") for h in hits[:3]]
                if check_p3(query, top3):
                    correct += 1
            p3 = correct / len(queries) * 100 if queries else 0
            set_results[key] = {
                "correct": correct, "total": len(queries), "p3": round(p3, 1),
            }
            total_correct += correct
            total_queries += len(queries)

        overall_p3 = total_correct / total_queries * 100
        set_results["overall"] = {
            "correct": total_correct, "total": total_queries,
            "p3": round(overall_p3, 1),
        }
        results[str(alpha)] = set_results

    # 최적 α 선정 및 리포트 출력
    best_alpha = max(results, key=lambda a: results[a]["overall"]["p3"])
    # ... (리포트 출력 + JSON 저장)
    return results
```

### 2-3. 실행 방법

```bash
# Docker 컨테이너 내부에서 실행
python3 codes/query/test_query_decomposition.py \
    --alpha-grid \
    --output results/alpha_grid.json
```

### 2-4. 기대 결과 예시

```
  α Grid Search 결과 종합
  ────────────────────────────────────────────────
  α        Set A    Set B    Set C    Set D    Set E    전체
  ────────────────────────────────────────────────
  0.30     78.0%   58.0%   80.0%   57.0%   54.0%   67.4%
  0.35     78.7%   58.0%   80.0%   57.0%   54.0%   67.6%
  0.40     79.3%   58.0%   81.0%   57.0%   55.0%   68.2%   ← REWRITE 적합
  0.45     79.3%   56.0%   81.0%   57.0%   55.0%   68.0%
  0.50     79.0%   56.0%   81.0%   57.0%   55.0%   68.0%   ← 현재
  0.55     79.3%   54.0%   81.0%   56.0%   55.0%   67.6%
  0.60     80.0%   52.0%   81.0%   56.0%   55.0%   67.6%
  0.65     80.0%   50.0%   82.0%   55.0%   55.0%   67.4%
  0.70     80.7%   48.0%   82.0%   54.0%   55.0%   67.2%   ← SIMPLE_FORMAL 적합

  최적 α = 0.40 (전체 P@3 = 68.2%)
```

**핵심 통찰**: 전역 최적 α는 하나의 값이지만, **Set A는 α↑에서 좋아지고 Set B는 α↓에서 좋아진다** → Query-type별 조건부 α가 필요한 이유.

---

## 3. Step 1-B: Query-type별 조건부 α

### 3-1. 설계 원리

> **비유**: 수능에서 수학은 객관식 비중을 높이고, 국어는 서술식 비중을 높이는 것처럼, 질의 유형별로 CE의 비중을 다르게 설정한다.

**조건부 α 결정 로직**:

```
IF colloquial_score >= 2:       → α = 0.3 (CE 비중 최소)
ELIF SIMPLE + 정규 용어 2개 이상: → α = 0.7 (CE 비중 최대)
ELIF SIMPLE + 정규 용어 1개:     → α = 0.5 (기본값)
ELIF REWRITE:                   → α = 0.4 (RRF 보험 비중↑)
ELIF DECOMPOSE:                 → α = 0.5 (기본값)
```

### 3-2. colloquial_score란?

> **비유**: "이 사람이 얼마나 캐주얼하게 말하는지" 점수. 높을수록 비격식적인 질의.

```python
def _colloquial_score(self, query: str) -> int:
    """구어체 마커 수를 카운팅. 높을수록 구어체."""
    # 1단계: 구어체 마커 개수 세기
    score = sum(1 for m in COLLOQUIAL_MARKERS if m in query)
    # COLLOQUIAL_MARKERS = ["뭐야", "어쩌", "어떡", "알려줘", "해줘",
    #                        "프로까지", "빌려", "떼가", "나라에", ...]

    # 2단계: 전문용어가 하나도 없으면 +2
    if not self._find_matching_terms(query):
        score += 2

    return score
```

예시:
- "취득세 감면 대상" → score=0 (마커 0개, 전문용어 있음)
- "세금 얼마야" → score=0 (마커 0개, "세금"은 전문용어)
- "나라에 돈 내야 되나" → score=3 ("나라에" 1개 + 전문용어 없음 +2)

### 3-3. 구현 코드

`codes/query/config.py`:

```python
# ────────── Phase 2A: CE 점수 퓨전 α 조건부 설정 ──────────
ALPHA_BY_QUERY_TYPE = {
    "SIMPLE_FORMAL":  0.7,   # 정규 용어 2+ → CE 신뢰
    "SIMPLE_MIXED":   0.5,   # 정규 용어 1개 → 기본값
    "REWRITE":        0.4,   # 구어체 변환 → RRF 비중↑
    "DECOMPOSE":      0.5,   # 복합 분해 → 기본값
}
ALPHA_COLLOQUIAL_OVERRIDE = 0.3  # colloquial_score >= 2
```

`codes/query/pipeline.py`:

```python
def _resolve_alpha(self, analysis: QueryAnalysis, query: str) -> float:
    """Phase 2A: 질의 분석 결과에 따라 최적 α 결정."""
    # 1순위: 극단 구어체 감지 시 CE 비중 최소
    cs = self.analyzer._colloquial_score(query)
    if cs >= 2:
        return ALPHA_COLLOQUIAL_OVERRIDE  # 0.3

    # 2순위: SIMPLE 질의의 세분화
    if analysis.type == "SIMPLE":
        matched = self.analyzer._find_matching_terms(query)
        if len(matched) >= 2:
            return ALPHA_BY_QUERY_TYPE["SIMPLE_FORMAL"]  # 0.7
        return ALPHA_BY_QUERY_TYPE["SIMPLE_MIXED"]  # 0.5

    # 3순위: REWRITE/DECOMPOSE
    return ALPHA_BY_QUERY_TYPE.get(analysis.type, 0.5)
```

**호출 지점** — `search()` 메서드에서:

```python
# search() 내부
effective_alpha = rerank_alpha  # 외부에서 명시적 전달 시 우선
skip_rerank = False
if rerank:
    skip_rerank = self._should_skip_rerank(analysis, query)
    if not skip_rerank and rerank_alpha == 0.5:  # 기본값이면 자동 결정
        effective_alpha = self._resolve_alpha(analysis, query)
```

### 3-4. 세트별 기대 효과

| 세트 | 주요 α | 이유 | 기대 변화 |
|------|-------|------|---------|
| A (정규) | 0.7 | 대부분 SIMPLE_FORMAL → CE 강화 | +1%p |
| B (구어체) | 0.3 | colloquial_score ≥ 2 → CE 약화 | +2%p |
| C (크로스) | 0.5 | 혼합 → 기본값 유지 | 0%p |
| D (구어체) | 0.3~0.4 | REWRITE 비중 높음 | +1%p |
| E (슬랭) | 0.4 | REWRITE 빈도 높음 | +0.5%p |

---

## 4. 검증 계획

### 4-1. α 그리드 서치 검증

```bash
# 1. α 그리드 서치 실행
python3 test_query_decomposition.py --alpha-grid --output results/alpha_grid.json

# 2. 결과 분석: 세트별 최적 α 확인
# Set A 최적 α, Set B 최적 α, 전체 최적 α
```

### 4-2. 조건부 α 통합 검증

```bash
# 조건부 α가 적용된 full_rerank 벤치마크
python3 test_query_decomposition.py --setting full_rerank --output results/phase2a_step1.json
```

**성공 기준**:
- 전체 P@3 ≥ 69.0% (현재 68.0% 대비 +1%p)
- Set A P@3 ≥ 79% (회귀 없음)
- Set B P@3 ≥ 58% (Full 수준 이상)
