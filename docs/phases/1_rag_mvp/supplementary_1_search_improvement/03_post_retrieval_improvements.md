# Sprint 2: Post-Retrieval 개선 — CRAG & Listwise LLM Reranking

> 목적: 검색 **이후** 단계에서 결과 품질을 개선하는 2가지 기법의 알고리즘 설계와 핵심 코드
> 수정 대상 파일: `codes/query/pipeline.py`, `codes/query/config.py`, `codes/query/prompts.py`

---

## 1. CRAG (Corrective Retrieval Augmented Generation) — 현재 상태 및 개선 방향

> **이미 구현 완료**: `codes/query/compensator.py` (RetrievalEvaluator + RetrievalCompensator)
> **파이프라인 통합**: `pipeline.py`의 `_apply_crag()` 메서드
> **Phase 2 결과**: 단일 파이프라인에서 세트별 효과가 상쇄되어 전체 P@3 기여 +0%p
> **현재 설정**: `CRAG_SCORE_THRESHOLD_CORRECT=0.90`, `CRAG_SCORE_THRESHOLD_SKIP=0.75`

### 1-0. 현재 구현 요약

현재 CRAG 파이프라인:

```
검색 결과 top-3 → [RetrievalEvaluator]
    │
    ├── Tier 1 Fast Path (rule-based):
    │   ├── top-1 score ≥ 0.90 → CORRECT (자동 통과)
    │   └── top-1 score ≥ 0.75 + 도메인 일치 → CORRECT
    │
    └── Tier 2 LLM 평가 (Claude Sonnet):
        ├── CORRECT → 그대로 통과
        ├── AMBIGUOUS → RetrievalCompensator: LLM 제안 용어로 재검색 + RRF 합산
        └── INCORRECT → RetrievalCompensator: 재검색

    RRF 가중치: 초기 결과 0.3, 보정 결과 1.0 (초기 오답 억제)
```

**Phase 2 테스트 결과**: CRAG가 Set D에서만 효과적이고 Set C/E에서 역효과 → 전체 net zero.

### 1-1. 추가 개선 방향

현재 파이프라인은 검색 결과를 **아무런 검증 없이** 그대로 LLM에 전달한다. 하지만 실제로는:

```
질의: "경매 낙찰되면 세금 내야해?"
          ↓
검색 결과 Top-3:
  [1] "법원경매 입찰 절차" (auction) — 세금 관련 아님 ❌
  [2] "경매 배당 순서" (auction) — 세금 관련 아님 ❌
  [3] "경매 취득세 납부" (tax) — 정답 ✅
```

정답이 3위에 있고 1-2위는 같은 도메인(경매)이지만 다른 주제다. LLM은 1-2위를 기반으로 "경매 절차에 대해서 설명해드리겠습니다"라고 엉뚱한 답변을 생성할 수 있다.

CRAG는 이런 상황에서 **"1-2위 결과는 질문과 관련 없다"**고 판단하여 걸러내거나, 다른 컬렉션에서 재검색한다.

### 1-2. 추가 개선 알고리즘 — 메타데이터 기반 사전 필터

현재 CRAG의 Tier 1은 **점수 임계값** 기반이다. 추가로 **메타데이터(branch/도메인) 일치** 기반 사전 필터를 도입하면 LLM 호출을 줄이면서 정밀도를 높일 수 있다:

```
검색 결과 top-K
       │
       ▼
[관련성 평가기 (Relevance Evaluator)]
       │
       ├─── {CORRECT} ← 상위 결과의 도메인이 질의 도메인과 일치
       │         └── 그대로 통과
       │
       ├─── {AMBIGUOUS} ← 부분 일치 (일부만 관련)
       │         └── Knowledge Refinement: 관련 문장만 추출
       │
       └─── {INCORRECT} ← 도메인 불일치
                  └── Fallback: 다른 컬렉션에서 재검색
```

> **핵심 개념 — 관련성 평가(Relevance Evaluation)란?**
>
> "검색 결과가 정말 질문에 답할 수 있는가?"를 판단하는 것이다.
>
> **비유**: 도서관에서 "부동산 세금" 관련 책을 찾으려는데, 사서가 "부동산 경매" 관련 책을 가져왔다면, "이건 제가 찾는 것과 다릅니다"라고 말하고 다시 찾아달라고 하는 과정이다.

### 1-3. 관련성 평가 로직 — 메타데이터 기반 (LLM 불필요)

현재 시스템에서는 LLM 호출 없이 **메타데이터만으로** 관련성을 평가할 수 있다. 이유: 온톨로지 컬렉션의 모든 청크에 `branch` (도메인) 필드가 있고, `QueryAnalyzer._detect_domains()`가 질의에서 도메인을 감지할 수 있다.

```python
from dataclasses import dataclass
from enum import Enum


class RetrievalConfidence(Enum):
    """검색 결과의 관련성 등급."""
    CORRECT = "correct"         # 상위 결과가 질의 도메인과 일치
    AMBIGUOUS = "ambiguous"     # 부분 일치 (일부만 관련)
    INCORRECT = "incorrect"     # 도메인 불일치


@dataclass
class CRAGEvaluation:
    """CRAG 평가 결과."""
    confidence: RetrievalConfidence
    relevant_indices: list[int]       # 관련 있는 결과의 인덱스
    missing_domains: list[str]        # 미커버 도메인
    reason: str


def evaluate_retrieval(
    results: list,
    query_domains: list[str],
    threshold_correct: float = 0.6,     # 상위 결과 60%+ 일치 → CORRECT
    threshold_ambiguous: float = 0.2,   # 20%+ 일치 → AMBIGUOUS
) -> CRAGEvaluation:
    """검색 결과의 관련성을 메타데이터 기반으로 평가.

    Args:
        results: Qdrant 검색 결과 (ScoredPoint 리스트)
        query_domains: QueryAnalyzer._detect_domains()로 감지된 도메인 목록
        threshold_correct: CORRECT 판정 임계값 (일치 비율)
        threshold_ambiguous: AMBIGUOUS 판정 임계값

    Returns:
        CRAGEvaluation: 관련성 등급 + 관련 결과 인덱스 + 미커버 도메인

    예시:
        질의 도메인: ["tax", "auction"]
        결과 도메인: ["auction", "auction", "tax", "auction", "loan"]
        일치: 3/5 = 0.6 → CORRECT
    """
    if not results or not query_domains:
        return CRAGEvaluation(
            confidence=RetrievalConfidence.CORRECT,
            relevant_indices=list(range(len(results))),
            missing_domains=[],
            reason="도메인 정보 부족 — 기본 통과",
        )

    query_domain_set = set(query_domains)
    relevant_indices = []
    result_domains = set()

    for i, point in enumerate(results):
        branch = point.payload.get("branch", "")
        result_domains.add(branch)
        if branch in query_domain_set:
            relevant_indices.append(i)

    match_ratio = len(relevant_indices) / len(results) if results else 0
    missing_domains = list(query_domain_set - result_domains)

    if match_ratio >= threshold_correct:
        return CRAGEvaluation(
            confidence=RetrievalConfidence.CORRECT,
            relevant_indices=relevant_indices,
            missing_domains=missing_domains,
            reason=f"도메인 일치 {match_ratio:.0%}",
        )
    elif match_ratio >= threshold_ambiguous:
        return CRAGEvaluation(
            confidence=RetrievalConfidence.AMBIGUOUS,
            relevant_indices=relevant_indices,
            missing_domains=missing_domains,
            reason=f"부분 일치 {match_ratio:.0%}, 미커버: {missing_domains}",
        )
    else:
        return CRAGEvaluation(
            confidence=RetrievalConfidence.INCORRECT,
            relevant_indices=relevant_indices,
            missing_domains=missing_domains,
            reason=f"도메인 불일치 {match_ratio:.0%}",
        )
```

> **왜 LLM 대신 메타데이터를 사용하는가?**
>
> 원본 CRAG 논문에서는 작은 분류기 모델(T5-large)을 사용하여 관련성을 평가한다. 하지만 우리 시스템에는:
> 1. 온톨로지의 10개 도메인 분류(`branch`)가 이미 모든 청크에 태깅되어 있음
> 2. `QueryAnalyzer._detect_domains()`가 질의에서 도메인을 감지할 수 있음
>
> 따라서 **LLM 호출 없이 메타데이터 비교만으로** CRAG의 핵심 아이디어를 구현할 수 있다. 이는 레이턴시와 비용을 절약하면서도 효과적이다.

### 1-4. Pipeline 통합 — `pipeline.py`에 CRAG 단계 추가

```python
# ─── 기존 구현 (pipeline.py, 이미 운영 중) ───
def _apply_crag(self, query, onto_results, analysis, limit):
    """CRAG 보정 적용. (results, grade, retries) 반환."""
    if not CRAG_ENABLED or not onto_results:
        return onto_results, "", 0
    from compensator import RetrievalEvaluator, RetrievalCompensator
    evaluator = RetrievalEvaluator(model=self.analyzer.model, analyzer=self.analyzer)
    evaluation = evaluator.evaluate(query, onto_results[:3], analysis)
    if evaluation.grade == "CORRECT":
        return onto_results, evaluation.grade, 0
    compensator = RetrievalCompensator(self.qdrant, self.analyzer)
    compensated = compensator.compensate(query, onto_results, evaluation, limit)
    return compensated, evaluation.grade, 1

# ─── 추가 개선: 메타데이터 기반 사전 필터 (신규) ───
# evaluate_retrieval() 함수를 Tier 0로 추가하여
# LLM 호출 전에 도메인 불일치를 빠르게 감지
```

### 1-5. search() 메서드에 CRAG 통합

```python
def search(self, query: str, limit: int = 5,
           crag: bool = False,     # CRAG 활성화 여부
           **kwargs) -> PipelineResult:
    # ... 기존 검색 + RRF + 리랭킹 로직 ...

    # CRAG 교정 (리랭킹 이후, 최종 반환 전)
    if crag:
        onto_final, legal_final = self._apply_crag(
            query, analysis, onto_final, legal_final, limit
        )

    return PipelineResult(
        ontology_results=onto_final,
        legal_results=legal_final,
        # ...
    )
```

---

## 2. Listwise LLM Reranking

### 2-1. 문제 정의 — CE 양극화 상세

Cross-Encoder(CE)의 BCE(Binary Cross-Entropy) loss 학습 방식의 부작용:

```
CE 점수 분포 (Phase 2 테스트):
  0.0 근처: 70%의 후보  ← "관련 없음"으로 극단 판정
  0.9~1.0: 18%의 후보   ← "매우 관련"으로 극단 판정
  0.01~0.89: 12%만      ← 중간 값이 거의 없음 (양극화)
```

> **핵심 개념 — Binary Cross-Entropy (BCE) Loss란?**
>
> 분류 문제에서 사용되는 손실 함수로, 모델의 출력을 0(무관) 또는 1(관련)에 가깝도록 학습시킨다.
>
> **비유**: 시험 채점을 "합격(1) / 불합격(0)"으로만 하도록 훈련받은 채점관은, "70점짜리 답안"과 "30점짜리 답안"을 구분하기 어렵다. 둘 다 "불합격(0)"으로 처리하기 때문이다.
>
> CE 모델도 마찬가지로, "약간 관련 있는" 문서와 "전혀 관련 없는" 문서를 둘 다 0.0x 점수로 평가해버려, 미묘한 차이를 구분하지 못한다.

구어체 질의에서의 문제:

```
질의: "부동산 사면 나라에 돈 내야 되나" (구어체)

CE 점수:
  [1위] "부동산 중개수수료" → CE: 0.03  ← 오답이지만 미세하게 높음
  [2위] "취득세 납부 의무"  → CE: 0.01  ← 정답인데 더 낮음!

원인: 구어체 질의와 전문 문서 사이의 어휘 격차가 커서 CE가 양쪽 모두
"관련 없음(0.0x)"으로 판정. 그 안에서의 미세한 차이는 노이즈일 뿐.
```

**현재 해결 (Phase 2A 완료)**: `_should_skip_rerank()`로 극단 구어체(colloquial_score ≥ 2)에서 CE 스킵. `REWRITE_SKIP_THRESHOLD=1`로 REWRITE + 슬랭 마커 1개면 CE 스킵. 이로써 Set B: 46%→60% (+14%p) 달성. 하지만 CE **스킵**은 리랭킹 이점을 완전히 포기하는 것이다.

### 2-2. Listwise LLM Reranking 알고리즘

```
기존 검색 + RRF 합산 → top-5 후보
          │
          ▼
  [CE 스킵 조건 확인]
          │
          ├─── CE 적용 가능 → 기존 CE 리랭킹
          │
          └─── CE 스킵 대상 (극단 구어체) → Listwise LLM Reranking
                    │
                    ▼
              LLM에 질의 + 5개 후보를 한꺼번에 제시
                    │
                    ▼
              LLM이 관련도 순위 반환 [3, 1, 5, 2, 4]
                    │
                    ▼
              순위대로 재정렬
```

> **Pointwise vs Listwise 리랭킹 비교**
>
> | 방식 | 입력 | 출력 | 장점 | 단점 |
> |------|------|------|------|------|
> | **Pointwise** (현재 CE) | (질의, 문서1), (질의, 문서2), ... | 각각 독립 점수 | 빠름, 확장 가능 | 문서 간 비교 불가 |
> | **Listwise** (LLM) | (질의, [문서1, 문서2, ...]) | 전체 순위 | 상대 비교 가능 | 느림, 비용 |
>
> **비유**:
> - Pointwise: 100m 달리기를 각자 따로 뛰고 기록만 비교
> - Listwise: 결승전에서 5명이 함께 뛰며 직접 순위를 매김

### 2-3. Listwise Reranking 프롬프트 — `prompts.py`

```python
LISTWISE_RERANK_PROMPT = """당신은 대한민국 부동산 검색 결과 평가 전문가입니다.

사용자 질문에 가장 관련 있는 순서대로 검색 결과를 정렬하세요.

## 평가 기준
1. 질문이 묻는 **핵심 주제**에 직접 답할 수 있는가
2. 구어체 표현이라면 그 뜻에 해당하는 **전문 개념**인가
3. 동일 도메인이더라도 **구체적인 질문 의도**와 일치하는가

## 사용자 질문
{query}

## 검색 결과
{candidates}

## 응답 형식
관련도가 높은 순서대로 결과 번호만 나열하세요. 예: [3, 1, 5, 2, 4]
번호만 JSON 배열로 반환하세요."""


def format_candidates_for_rerank(results: list, max_candidates: int = 5) -> str:
    """검색 결과를 LLM 프롬프트용 텍스트로 포맷."""
    lines = []
    for i, point in enumerate(results[:max_candidates]):
        term = point.payload.get("term", "")
        description = point.payload.get("description", "")[:200]
        branch = point.payload.get("branch", "")

        lines.append(f"[{i+1}] {term} ({branch})")
        if description:
            lines.append(f"    {description}")
        lines.append("")

    return "\n".join(lines)
```

### 2-4. Listwise Reranking 함수 — `pipeline.py`

```python
def _listwise_llm_rerank(
    self,
    query: str,
    candidates: list,
    top_k: int = 5,
) -> list:
    """Listwise LLM Reranking: CE 양극화 대안.

    CE가 스킵되는 극단 구어체 질의에 대해,
    LLM을 사용하여 top-5 후보를 listwise 재정렬.

    Args:
        query: 원본 사용자 질의
        candidates: 검색 결과 (이미 RRF 정렬됨)
        top_k: 재정렬 후 반환할 결과 수

    Returns:
        재정렬된 결과 리스트
    """
    if len(candidates) <= 1:
        return candidates[:top_k]

    # 최대 5개만 LLM에 제시 (토큰 절약)
    rerank_pool = candidates[:5]

    from prompts import LISTWISE_RERANK_PROMPT, format_candidates_for_rerank

    candidates_text = format_candidates_for_rerank(rerank_pool)
    prompt = LISTWISE_RERANK_PROMPT.format(
        query=query,
        candidates=candidates_text,
    )

    try:
        raw = self.analyzer._call_claude_cli(prompt)

        # JSON 배열 파싱: [3, 1, 5, 2, 4]
        import re
        arr_match = re.search(r'\[[\d,\s]+\]', raw)
        if arr_match:
            ranking = json.loads(arr_match.group())

            # 1-indexed → 0-indexed, 범위 검증
            reordered = []
            seen = set()
            for idx in ranking:
                zero_idx = idx - 1
                if 0 <= zero_idx < len(rerank_pool) and zero_idx not in seen:
                    reordered.append(rerank_pool[zero_idx])
                    seen.add(zero_idx)

            # 누락된 후보 추가 (LLM이 일부를 빠뜨린 경우)
            for i, cand in enumerate(rerank_pool):
                if i not in seen:
                    reordered.append(cand)

            return reordered[:top_k]

    except Exception as e:
        print(f"[Listwise Rerank] 실패, 원본 순서 유지: {e}")

    return candidates[:top_k]
```

### 2-5. `_should_skip_rerank()` 수정 — CE 스킵 → Listwise 분기

```python
def _rerank_ontology(
    self,
    query: str,
    candidates: list,
    top_k: int = 5,
    alpha: float = 0.5,
    use_listwise: bool = False,   # 신규 파라미터
) -> list:
    """리랭킹: CE 또는 Listwise LLM 방식 선택."""
    if not candidates:
        return []

    if use_listwise:
        # CE 양극화가 예상되는 경우 → Listwise LLM
        return self._listwise_llm_rerank(query, candidates, top_k)

    # 기존 CE 리랭킹 로직
    reranked = rerank_results(query, candidates, top_k=len(candidates))
    # ... 기존 alpha fusion 로직 ...
```

```python
# search() 메서드에서 리랭킹 분기 수정
if rerank and onto_final:
    skip_rerank = self._should_skip_rerank(analysis, query)

    if skip_rerank and LISTWISE_RERANK_ENABLED:
        # CE 스킵 대상이지만 Listwise LLM으로 대체
        onto_final = self._rerank_ontology(
            query, onto_final, top_k=limit, use_listwise=True,
        )
    elif not skip_rerank:
        # 일반 CE 리랭킹
        onto_final = self._rerank_ontology(
            query, onto_final[:rerank_candidates],
            top_k=limit, alpha=effective_alpha,
        )
    # skip_rerank and not LISTWISE_RERANK_ENABLED → 리랭킹 없이 통과
```

### 2-6. `config.py`에 추가할 상수

```python
# ────────────── CRAG 설정 ──────────────────────
CRAG_ENABLED = True                        # CRAG 활성화 여부
CRAG_THRESHOLD_CORRECT = 0.6              # 상위 60%+ 도메인 일치 → CORRECT
CRAG_THRESHOLD_AMBIGUOUS = 0.2            # 20%+ 일치 → AMBIGUOUS

# ────────────── Listwise LLM Reranking 설정 ────
LISTWISE_RERANK_ENABLED = True             # Listwise Reranking 활성화 여부
LISTWISE_MAX_CANDIDATES = 5               # LLM에 제시할 최대 후보 수
```

---

## 3. 실행 순서

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **1** | `config.py`에 CRAG/Listwise 상수 추가 | — |
| **2** | `prompts.py`에 Listwise 프롬프트 추가 | — |
| **3** | `pipeline.py`에 `evaluate_retrieval()` + `_apply_crag()` 추가 | 1 |
| **4** | `pipeline.py`에 `_listwise_llm_rerank()` 추가 | 2 |
| **5** | `search()`에 CRAG + Listwise 분기 통합 | 3, 4 |
| **6** | 25개 질의 스모크 테스트 (CRAG ON/OFF, Listwise ON/OFF) | 5 |
| **7** | 500개 벤치마크 ablation 실행 | 6 |

---

## 4. 기대 효과 및 검증

### 4-1. 기법별 기대 효과

| 기법 | 주요 영향 | 기대 개선 | 추가 레이턴시 | 추가 비용 |
|------|----------|----------|-------------|----------|
| CRAG (기존) | 세트별 상쇄 | **이미 적용** (+0%p net) | ~14초 (LLM 평가) | ~$0.005/질의 |
| CRAG 개선 (메타 사전필터) | Set C/E 역효과 해소 | P@3 +1-2%p | ~20ms (메타 비교) | 무시 |
| Listwise LLM | Set B/D (극단 구어체) | P@3 +3-5% | ~1-2초 (LLM) | ~$0.003/질의 |

### 4-2. 벤치마크 비교 계획

```bash
# CRAG ablation
python3 benchmark.py --setting C --crag > crag_on.json

# Listwise ablation (CE 스킵 대상 질의만 비교)
python3 benchmark.py --setting E --listwise-rerank > listwise_on.json

# Sprint 1 + Sprint 2 통합
python3 benchmark.py --setting C --hyde --rag-fusion --dynamic-alpha \
                     --crag --listwise-rerank > sprint1_2_combined.json
```

### 4-3. 위험 요소

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| CRAG 오판정 (CORRECT를 INCORRECT로) | 중 | 정답 결과 제거 | threshold 보수적 설정 (0.6/0.2) |
| Listwise LLM이 잘못된 순위 반환 | 저 | 순위 악화 | 파싱 실패 시 원본 순서 유지 (fallback) |
| 도메인 감지 실패 (query_domains 빈 배열) | 중 | CRAG 무효화 | 빈 배열이면 CORRECT로 기본 통과 |
| Listwise의 비용/레이턴시 | 중 | 사용자 대기 | CE 스킵 대상(~40% 질의)에만 적용, 나머지는 기존 CE |
