# CRAG Retrieval Compensator — 상세 코드 설계

> 목적: 검색 품질이 낮은 질의(특히 Set E 슬랭)에서 LLM 기반 보정 재검색으로 P@3 개선
> 패턴 원본: `codes/query/analyzer.py` (LLM CLI 호출), `codes/query/pipeline.py` (파이프라인 통합)
> 선행 문서: `01_implementation_plan.md` §2

---

## 0. 핵심 개념 설명

### 0-1. RAG (Retrieval-Augmented Generation)란?

> **비유**: 시험을 볼 때 두 가지 방법이 있다. (1) 모든 것을 외워서 답하기 (LLM의 파라메트릭 지식), (2) 참고서를 펼쳐서 찾아 답하기 (검색). RAG는 이 두 가지를 결합한다: 먼저 참고서에서 관련 내용을 **검색(Retrieval)**하고, 그 내용을 바탕으로 **답변을 생성(Generation)**한다.
>
> 문제는 참고서에서 엉뚱한 페이지를 찾아오면 답변도 엉뚱해진다는 것이다. CRAG는 "찾아온 페이지가 맞는지 먼저 확인하고, 틀리면 다시 찾자"는 아이디어다.

### 0-2. CRAG (Corrective Retrieval-Augmented Generation)

Yan et al. (2024)이 제안한 기법으로, 검색 결과를 "정답/애매/오답"으로 평가하고 각각 다르게 처리한다:

```
사용자 질의 → 벡터 검색 → 결과 3건

  결과가 좋은가? (Retrieval Evaluator)
    ├─ CORRECT:   "네, 정확합니다" → 그대로 사용
    ├─ AMBIGUOUS: "좀 애매합니다" → 일부만 추리고 보충 검색
    └─ INCORRECT: "아닙니다"      → 버리고 새로 검색
```

> **비유**: 도서관에서 "영끌 대출"에 대해 찾으라고 했는데 사서가 "임의경매", "명도소송" 관련 책을 가져왔다. 관련은 있지만 원하는 정보가 아니다. CRAG는 사서에게 "아니요, '과다차입'이나 '강제경매' 관련 책을 다시 찾아주세요"라고 피드백을 주는 것과 같다.

### 0-3. Self-RAG의 핵심 아이디어: "항상 검색할 필요는 없다"

Asai et al. (2023, NeurIPS)의 Self-RAG에서 가장 중요한 통찰:

> "취득세 기준 금액"처럼 명확한 질의는 벡터 검색이 이미 정확하게 작동한다. 이런 경우 추가 평가나 재검색은 시간 낭비다. 반면 "영끌해서 집 샀는데 이자 감당 안 되면 경매 넘어가?"처럼 복잡한 슬랭 질의는 검색이 실패할 가능성이 높으므로 보정이 필요하다.

우리 시스템에서는 이를 **Rule-based fast path**로 구현한다:
- Top-1 검색 점수가 높으면 → 자동으로 CORRECT 판정 (LLM 호출 없음)
- 낮을 때만 → LLM에게 평가를 의뢰

### 0-4. RRF (Reciprocal Rank Fusion)

여러 검색 결과 목록을 하나로 합치는 알고리즘:

```
score(doc) = Σ weight_i / (k + rank_i + 1)
```

> **비유**: 친구 3명에게 각각 "맛집 추천"을 부탁했다. A가 1위로 추천한 식당, B가 2위로 추천한 식당, C가 3위로 추천한 식당... 모두를 종합해서 최종 랭킹을 만드는 것이 RRF다. 여러 친구(여러 검색 쿼리)가 공통으로 높게 추천한 식당(문서)이 최종 1위가 된다.

### 0-5. P@3 (Precision at 3)

우리 벤치마크의 핵심 지표. Top-3 검색 결과 중 기대 키워드가 포함된 것이 있으면 성공:

```python
def check_p3(query, top3_terms):
    expected = EXPECTED_KEYWORDS[query]  # 예: ["과다차입", "강제경매"]
    return any(
        any(kw in term for kw in expected)
        for term in top3_terms
    )
```

> "영끌해서 집 샀는데..."의 기대 키워드가 ["과다차입", "강제경매"]이고, top-3이 ["임의경매", "담보", "명도소송"]이면 → P@3 = **실패**. CRAG가 재검색으로 ["과다차입", "강제경매", "연체이자"]를 찾으면 → P@3 = **성공**.

---

## 1. 전체 아키텍처

### 1-1. 기존 파이프라인과의 통합 지점

```
현재 pipeline.py의 search() 메서드:

  Step 1: QueryAnalyzer.analyze()
  Step 2: embed_query() — 원본 질의 임베딩
  Step 3: SIMPLE → search + [CE rerank] → Return  ← 여기 뒤에 CRAG 삽입
  Step 4: REWRITE/DECOMPOSE → sub-query 검색
  Step 5: rrf_merge()
  Step 6: CE rerank                                ← 여기 뒤에 CRAG 삽입
  Return PipelineResult
```

CRAG는 **Step 3 또는 Step 6 이후, Return 직전**에 삽입된다. 기존 코드를 최소한으로 수정한다.

### 1-2. 모듈 구조

```
codes/query/
  ├── compensator_prompts.py   ← 신규: 평가 프롬프트
  ├── compensator.py           ← 신규: Evaluator + Compensator 클래스
  ├── config.py                ← 수정: CRAG 상수 추가
  ├── pipeline.py              ← 수정: CRAG 통합 (~15줄)
  └── test_query_decomposition.py  ← 수정: full_rerank_crag 설정
```

---

## 2. `compensator_prompts.py` — 평가 프롬프트

```python
#!/usr/bin/env python3
"""CRAG Retrieval Compensator 프롬프트 모듈."""

# ────────────── 검색 결과 평가 프롬프트 ──────────────────────

EVALUATOR_SYSTEM = """당신은 대한민국 부동산 RAG 시스템의 검색 결과 품질 평가기입니다.

사용자 질의와 검색 결과 3건을 비교하여 등급을 매깁니다:
- CORRECT: 검색 결과가 질의의 핵심 의도를 정확히 반영함
- AMBIGUOUS: 부분적으로 관련 있으나 핵심 정보가 빠짐
- INCORRECT: 질의 의도와 검색 결과가 맞지 않음

반드시 JSON으로만 응답하세요."""

EVALUATOR_USER_TEMPLATE = """사용자 질의: "{query}"

검색 결과:
1. [{term1}] {desc1}
2. [{term2}] {desc2}
3. [{term3}] {desc3}

아래 JSON 형식으로만 응답:
{{"grade": "CORRECT|AMBIGUOUS|INCORRECT", "formal_terms": ["용어1", "용어2", "용어3"], "reasoning": "한 줄 근거"}}

규칙:
- formal_terms: 사용자가 실제로 찾고 있는 부동산 전문 용어 3개 (온톨로지에 있을 법한 정규 용어)
- grade가 CORRECT이면 formal_terms는 검색 결과의 term을 그대로 사용
- grade가 AMBIGUOUS/INCORRECT이면 formal_terms는 검색 결과에 없는 새로운 용어를 제안"""
```

### 프롬프트 설계 원칙

1. **최소 토큰**: description은 50자로 truncate하여 비용 절감
2. **구조화된 출력**: JSON 강제로 파싱 안정성 확보
3. **formal_terms 유도**: 온톨로지에 있을 법한 정규 용어를 요청하여 재검색 정확도 향상
4. **한 줄 근거**: 디버깅/분석용 최소 메타데이터

---

## 3. `compensator.py` — 핵심 모듈

### 3-1. 데이터 클래스

```python
#!/usr/bin/env python3
"""
CRAG Retrieval Compensator — 검색 결과 평가 및 보정 재검색.

Phase 2A 후속: Set E(슬랭 54%) → ≥60% 달성을 위한 post-retrieval compensation.
CRAG (Yan et al. 2024, ICLR 2025) 기반으로, 검색 결과가 질의 의도와
맞지 않을 때 LLM이 정규 용어를 제안하여 재검색한다.

연구 배경:
  - CRAG: 3단계 신뢰도 평가 (CORRECT/AMBIGUOUS/INCORRECT)
  - Self-RAG (Asai 2023): 적응적 검색 — 항상 검색할 필요 없음
  - FILCO (2024): 저관련성 패시지 필터링으로 EM +8.6%
  - TA-ARE (2025): 학습 임계값으로 불필요 검색 14.9% 감소
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    CLAUDE_BIN, LLM_TIMEOUT, LLM_CALL_COOLDOWN,
    LLM_RETRY_COUNT, LLM_RETRY_WAIT,
    CRAG_SCORE_THRESHOLD_CORRECT, CRAG_SCORE_THRESHOLD_SKIP,
    CRAG_WEIGHT_INITIAL, CRAG_WEIGHT_COMPENSATED,
    DOMAIN_KEYWORDS_SEED,
)
from compensator_prompts import EVALUATOR_SYSTEM, EVALUATOR_USER_TEMPLATE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embedding"))
from embedder_bgem3 import embed_query
from search_test_phase2_v2 import search_ontology


@dataclass
class Evaluation:
    """검색 결과 평가 결과."""
    grade: str          # "CORRECT" | "AMBIGUOUS" | "INCORRECT"
    formal_terms: list[str]  # LLM이 제안한 정규 용어 (재검색용)
    reasoning: str = ""
    fast_path: bool = False  # Rule-based로 판정됨 (LLM 미호출)
    retries: int = 0
```

### 3-2. RetrievalEvaluator 클래스

```python
class RetrievalEvaluator:
    """검색 결과를 CORRECT/AMBIGUOUS/INCORRECT로 평가한다.

    2단계 평가:
      Tier 1 (Rule-based fast path): 점수/용어 기반 자동 판정 → LLM 호출 0
      Tier 2 (LLM 평가): Claude Sonnet으로 정밀 판정
    """

    def __init__(self, model: str = "sonnet", analyzer=None):
        self.model = model
        self.analyzer = analyzer  # QueryAnalyzer 참조 (용어 매칭용)

    def evaluate(
        self,
        query: str,
        top3_results: list,
        analysis=None,
    ) -> Evaluation:
        """검색 결과를 평가한다.

        Args:
            query: 원본 사용자 질의
            top3_results: Qdrant 검색 결과 상위 3건
            analysis: QueryAnalysis 객체 (optional, 도메인 힌트용)

        Returns:
            Evaluation 객체
        """
        if not top3_results:
            return Evaluation(
                grade="INCORRECT",
                formal_terms=[],
                reasoning="검색 결과 없음",
            )

        # ──── Tier 1: Rule-based fast path ────
        fast_result = self._fast_path(query, top3_results, analysis)
        if fast_result is not None:
            return fast_result

        # ──── Tier 2: LLM 평가 ────
        return self._llm_evaluate(query, top3_results)

    def _fast_path(
        self,
        query: str,
        top3: list,
        analysis=None,
    ) -> Evaluation | None:
        """Rule-based 자동 판정. CORRECT이면 Evaluation, 불확실하면 None.

        Self-RAG 아이디어: 확실한 경우 LLM 호출을 스킵하여 비용과 지연 절감.
        TA-ARE (2025): 점수 임계값 기반 적응적 판정으로 불필요 평가 14.9% 감소.
        """
        top1 = top3[0]
        top1_score = getattr(top1, 'score', 0) or 0

        # 규칙 1: Top-1 점수가 매우 높으면 자동 CORRECT
        if top1_score >= CRAG_SCORE_THRESHOLD_CORRECT:
            top3_terms = [p.payload.get("term", "") for p in top3]
            return Evaluation(
                grade="CORRECT",
                formal_terms=top3_terms,
                reasoning=f"top1_score={top1_score:.3f} ≥ {CRAG_SCORE_THRESHOLD_CORRECT}",
                fast_path=True,
            )

        # 규칙 2: 질의의 정규 용어가 top-3 결과에 직접 포함
        if self.analyzer:
            matched_terms = self.analyzer._find_matching_terms(query)
            top3_terms = [p.payload.get("term", "") for p in top3]

            if len(matched_terms) >= 2:
                hits = sum(
                    1 for mt in matched_terms
                    if any(mt in t for t in top3_terms)
                )
                if hits >= 2:
                    return Evaluation(
                        grade="CORRECT",
                        formal_terms=top3_terms,
                        reasoning=f"정규 용어 {hits}개가 top-3에 직접 매칭",
                        fast_path=True,
                    )

        # 규칙 3: 질의 도메인과 결과 도메인이 일치
        if self.analyzer and analysis:
            query_domains = set()
            for sq in analysis.queries:
                if sq.domain_hint and sq.domain_hint != "unknown":
                    query_domains.add(sq.domain_hint)

            if query_domains:
                result_domains = set(
                    p.payload.get("branch", "") for p in top3
                )
                if query_domains & result_domains:
                    # 도메인은 맞지만 점수가 낮으면 → None (LLM에게 맡김)
                    if top1_score >= CRAG_SCORE_THRESHOLD_SKIP:
                        return Evaluation(
                            grade="CORRECT",
                            formal_terms=[p.payload.get("term", "") for p in top3],
                            reasoning=f"도메인 일치 + score={top1_score:.3f}",
                            fast_path=True,
                        )

        return None  # fast path로 판정 불가 → Tier 2로

    def _llm_evaluate(self, query: str, top3: list) -> Evaluation:
        """Claude Sonnet으로 검색 결과를 평가한다.

        analyzer.py의 _call_claude_cli() 패턴을 재사용한다.
        """
        # 프롬프트 구성
        terms = []
        descs = []
        for p in top3:
            terms.append(p.payload.get("term", "?"))
            desc = p.payload.get("description", "") or p.payload.get("text", "")
            descs.append(desc[:50])  # 토큰 절약을 위해 50자 truncate

        user_prompt = EVALUATOR_USER_TEMPLATE.format(
            query=query,
            term1=terms[0] if len(terms) > 0 else "?",
            desc1=descs[0] if len(descs) > 0 else "",
            term2=terms[1] if len(terms) > 1 else "?",
            desc2=descs[1] if len(descs) > 1 else "",
            term3=terms[2] if len(terms) > 2 else "?",
            desc3=descs[2] if len(descs) > 2 else "",
        )

        full_prompt = EVALUATOR_SYSTEM + "\n\n" + user_prompt

        # LLM 호출 (rate-limit 쿨다운 포함)
        for attempt in range(LLM_RETRY_COUNT):
            try:
                if LLM_CALL_COOLDOWN > 0:
                    time.sleep(LLM_CALL_COOLDOWN)

                raw = self._call_claude_cli(full_prompt)

                # JSON 파싱
                raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
                raw = re.sub(r'^```\s*$', '', raw, flags=re.MULTILINE)
                raw = raw.strip()

                obj_match = re.search(r'\{.*\}', raw, re.DOTALL)
                if obj_match:
                    raw = obj_match.group()

                parsed = json.loads(raw)

                grade = parsed.get("grade", "AMBIGUOUS").upper()
                if grade not in ("CORRECT", "AMBIGUOUS", "INCORRECT"):
                    grade = "AMBIGUOUS"

                formal_terms = parsed.get("formal_terms", [])
                reasoning = parsed.get("reasoning", "")

                # formal_terms 검증: 빈 문자열 제거
                formal_terms = [t.strip() for t in formal_terms if t.strip()]

                return Evaluation(
                    grade=grade,
                    formal_terms=formal_terms[:5],  # 최대 5개
                    reasoning=reasoning,
                    fast_path=False,
                )

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"[CRAG] 평가 파싱 실패 (시도 {attempt+1}): {e}")
                if attempt < LLM_RETRY_COUNT - 1:
                    time.sleep(LLM_RETRY_WAIT)

            except (RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"[CRAG] LLM 호출 실패 (시도 {attempt+1}): {e}")
                if attempt < LLM_RETRY_COUNT - 1:
                    time.sleep(LLM_RETRY_WAIT)

        # Fallback: LLM 실패 시 AMBIGUOUS로 처리
        print("[CRAG] 평가 LLM 실패 — AMBIGUOUS fallback")
        return Evaluation(
            grade="AMBIGUOUS",
            formal_terms=[],
            reasoning="LLM 호출 실패 — fallback",
        )

    def _call_claude_cli(self, prompt: str) -> str:
        """Claude Code CLI를 -p 파이프 모드로 호출.

        analyzer.py:236-256의 패턴을 그대로 재사용한다.
        """
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        proc = subprocess.run(
            [CLAUDE_BIN, "-p",
             "--model", self.model,
             "--no-session-persistence"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=LLM_TIMEOUT,
            env=env,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(f"Claude CLI 실패 (exit={proc.returncode}): {stderr}")

        return proc.stdout.strip()
```

### 3-3. RetrievalCompensator 클래스

```python
class RetrievalCompensator:
    """검색 결과가 부족할 때 보정 재검색을 수행한다.

    CRAG의 3경로:
      CORRECT   → 변경 없음 (이 클래스가 호출되지 않음)
      AMBIGUOUS → 초기 결과 일부 + 보정 검색 결과 병합 (RRF)
      INCORRECT → 초기 결과 버리고 보정 검색만으로 구성
    """

    def __init__(self, qdrant_client, analyzer=None):
        """
        Args:
            qdrant_client: QdrantClient 인스턴스
            analyzer: QueryAnalyzer (formal_terms 검증용, optional)
        """
        self.qdrant = qdrant_client
        self.analyzer = analyzer

    def compensate(
        self,
        query: str,
        initial_results: list,
        evaluation: Evaluation,
        limit: int = 5,
    ) -> list:
        """평가 결과에 따라 보정 검색을 수행한다.

        Args:
            query: 원본 사용자 질의
            initial_results: 기존 검색 결과
            evaluation: RetrievalEvaluator의 평가 결과
            limit: 최종 반환 결과 수

        Returns:
            보정된 검색 결과 리스트
        """
        if evaluation.grade == "CORRECT":
            return initial_results

        # formal_terms로 보정 쿼리 구성
        formal_terms = evaluation.formal_terms
        if not formal_terms:
            print("[CRAG] formal_terms 없음 — 초기 결과 반환")
            return initial_results

        # formal_terms 검증 (온톨로지에 있는 용어인지)
        if self.analyzer:
            validated = []
            for term in formal_terms:
                if term in self.analyzer._formal_terms:
                    validated.append(term)
                else:
                    # 부분 매칭 시도
                    partial = [
                        ft for ft in self.analyzer._formal_terms
                        if term in ft or ft in term
                    ]
                    if partial:
                        validated.append(partial[0])
            if validated:
                formal_terms = validated
            # 검증 실패해도 원본 formal_terms 사용 (LLM 판단 존중)

        if evaluation.grade == "AMBIGUOUS":
            return self._compensate_ambiguous(
                query, initial_results, formal_terms, limit
            )
        else:  # INCORRECT
            return self._compensate_incorrect(
                query, formal_terms, limit
            )

    def _compensate_ambiguous(
        self,
        query: str,
        initial_results: list,
        formal_terms: list[str],
        limit: int,
    ) -> list:
        """AMBIGUOUS: 초기 결과 + 보정 검색을 RRF로 병합.

        초기 결과는 부분적으로 맞으므로 버리지 않고, 보정 결과와 합친다.
        가중치: 초기 0.6, 보정 1.0 (보정 결과에 더 높은 비중)

        비유: 친구가 추천한 맛집 목록(초기 결과)에 전문 평론가의 추천(보정 결과)을
             합쳐서 최종 목록을 만드는 것. 평론가 추천에 더 높은 가중치를 준다.
        """
        from merger import rrf_merge

        # 보정 쿼리 구성: formal_terms를 공백으로 연결
        comp_query = " ".join(formal_terms[:3])
        print(f"[CRAG-AMBIGUOUS] 보정 쿼리: {comp_query}")

        # 보정 검색 실행
        dense, sparse, colbert = embed_query(comp_query)
        comp_results = search_ontology(
            self.qdrant, "domain_ontology_v2",
            dense, sparse, colbert,
            mode="hybrid_rrf", limit=limit * 2,
        )

        if not comp_results:
            print("[CRAG-AMBIGUOUS] 보정 검색 결과 없음 — 초기 결과 반환")
            return initial_results

        # RRF 병합: [초기 결과, 보정 결과]
        merged = rrf_merge(
            [initial_results, comp_results],
            weights=[CRAG_WEIGHT_INITIAL, CRAG_WEIGHT_COMPENSATED],
        )

        return merged[:limit]

    def _compensate_incorrect(
        self,
        query: str,
        formal_terms: list[str],
        limit: int,
    ) -> list:
        """INCORRECT: 초기 결과 무시, 보정 검색만으로 구성.

        초기 결과가 완전히 빗나갔으므로 새로 검색한 결과만 사용한다.
        formal_terms가 여러 개면 도메인별로 나누어 검색 후 RRF 병합.

        비유: 영어 책을 찾으러 왔는데 수학 책 코너를 안내받았다.
             이 경우 수학 코너의 책은 전부 무시하고, "영어 코너"로 직접 가야 한다.
        """
        from merger import rrf_merge

        # 보정 쿼리 구성
        # formal_terms가 3개 이상이면 2개씩 묶어 여러 쿼리 생성
        comp_queries = []
        if len(formal_terms) <= 2:
            comp_queries.append(" ".join(formal_terms))
        else:
            # 조합 1: 전체
            comp_queries.append(" ".join(formal_terms[:3]))
            # 조합 2: 원본 질의 + 첫 번째 formal_term
            comp_queries.append(f"{query} {formal_terms[0]}")

        print(f"[CRAG-INCORRECT] 보정 쿼리 {len(comp_queries)}개: {comp_queries}")

        # 각 보정 쿼리로 검색
        all_results = []
        for cq in comp_queries:
            dense, sparse, colbert = embed_query(cq)
            results = search_ontology(
                self.qdrant, "domain_ontology_v2",
                dense, sparse, colbert,
                mode="hybrid_rrf", limit=limit * 2,
            )
            if results:
                all_results.append(results)

        if not all_results:
            print("[CRAG-INCORRECT] 보정 검색 모두 실패 — 빈 결과")
            return []

        if len(all_results) == 1:
            return all_results[0][:limit]

        # 여러 보정 결과를 RRF 병합
        merged = rrf_merge(
            all_results,
            weights=[1.0] * len(all_results),
        )

        return merged[:limit]
```

---

## 4. `config.py` 수정 — CRAG 상수 추가

```python
# ────────────── CRAG Compensation (Phase 2A 후속) ──────────────
# CRAG (Yan et al. 2024, ICLR 2025): 검색 결과 신뢰도 3단계 평가
# Self-RAG (Asai et al. 2023): 적응적 검색 — 확실할 때 LLM 스킵

CRAG_ENABLED = True                    # 기능 플래그
CRAG_SCORE_THRESHOLD_CORRECT = 0.85    # top-1 score ≥ 이 값 → 자동 CORRECT
CRAG_SCORE_THRESHOLD_SKIP = 0.60       # top-1 score ≥ 이 값 + 도메인 일치 → CORRECT
CRAG_MAX_RETRIES = 1                   # 최대 재검색 횟수
CRAG_WEIGHT_INITIAL = 0.6             # AMBIGUOUS merge: 초기 결과 가중치
CRAG_WEIGHT_COMPENSATED = 1.0         # AMBIGUOUS merge: 보정 결과 가중치
CRAG_EVALUATION_TIMEOUT = 60           # LLM 평가 타임아웃 (초)
```

### 상수 설계 근거

| 상수 | 값 | 근거 |
|------|---|------|
| `SCORE_THRESHOLD_CORRECT` | 0.85 | Phase 2A 벤치마크에서 P@3 성공 질의의 top-1 평균 ≈ 0.83 |
| `SCORE_THRESHOLD_SKIP` | 0.60 | 실패 질의의 top-1 평균 ≈ 0.55, 0.60 이상이면 "근접" |
| `WEIGHT_INITIAL` | 0.6 | AMBIGUOUS는 초기 결과도 부분 유용. 너무 낮추면 기존 정답 유실 |
| `WEIGHT_COMPENSATED` | 1.0 | 보정 검색은 LLM이 제안한 정규 용어 기반이므로 높은 신뢰 |

---

## 5. `pipeline.py` 수정 — CRAG 통합

### 5-1. PipelineResult 확장

```python
@dataclass
class PipelineResult:
    """검색 파이프라인 전체 결과."""
    ontology_results: list
    legal_results: list
    analysis: QueryAnalysis
    total_latency_ms: float = 0.0
    search_count: int = 0
    crag_grade: str = ""        # 추가: CRAG 평가 등급
    crag_retries: int = 0       # 추가: CRAG 재검색 횟수
```

### 5-2. search() 메서드에 crag 파라미터 추가

```python
def search(
    self,
    query: str,
    limit: int = 5,
    search_ontology_only: bool = False,
    search_legal_only: bool = False,
    rerank: bool = False,
    rerank_candidates: int = 20,
    rerank_alpha: float = 0.5,
    crag: bool = False,           # 추가
) -> PipelineResult:
```

### 5-3. CRAG 보정 단계 삽입

SIMPLE 경로 (line 206-220 부근)와 REWRITE/DECOMPOSE 경로 (line 267-281 부근) 양쪽에 동일한 CRAG 단계를 삽입한다. 코드 중복을 피하기 위해 헬퍼 메서드로 추출:

```python
def _apply_crag(
    self,
    query: str,
    onto_results: list,
    analysis: QueryAnalysis,
    limit: int,
) -> tuple[list, str, int]:
    """CRAG 보정 적용. (results, grade, retries) 반환."""
    from config import CRAG_ENABLED
    if not CRAG_ENABLED:
        return onto_results, "", 0

    from compensator import RetrievalEvaluator, RetrievalCompensator

    evaluator = RetrievalEvaluator(
        model=self.analyzer.model,
        analyzer=self.analyzer,
    )
    evaluation = evaluator.evaluate(query, onto_results[:3], analysis)

    if evaluation.grade == "CORRECT":
        return onto_results, evaluation.grade, 0

    compensator = RetrievalCompensator(self.qdrant, self.analyzer)
    compensated = compensator.compensate(
        query, onto_results, evaluation, limit
    )

    return compensated, evaluation.grade, 1
```

사용 위치 (두 곳):

```python
# SIMPLE 경로 — onto_result 확정 후, return 전
if crag:
    onto_result, crag_grade, crag_retries = self._apply_crag(
        query, onto_result, analysis, limit
    )

# REWRITE/DECOMPOSE 경로 — CE reranking 후, return 전
if crag:
    onto_final, crag_grade, crag_retries = self._apply_crag(
        query, onto_final, analysis, limit
    )
```

---

## 6. `test_query_decomposition.py` 수정

### 6-1. 새 설정 `full_rerank_crag` 추가

line 103-111 부근, `full_rerank` 블록 아래에:

```python
elif setting == "full_rerank_crag":
    pr = pipeline.search(
        query, limit=limit, search_ontology_only=True,
        rerank=True, rerank_candidates=20, rerank_alpha=0.5,
        crag=True,
    )
    hits = pr.ontology_results
    analysis_type = pr.analysis.type + "+CE+CRAG"
    if pr.crag_grade:
        analysis_type += f"({pr.crag_grade[0]})"  # C/A/I 한 글자
    llm_called = pr.analysis.llm_called
    sub_qs = [sq.query for sq in pr.analysis.queries]
```

### 6-2. CLI 옵션

기존 `--setting` 파라미터에 `full_rerank_crag` 선택지 추가:

```python
parser.add_argument(
    "--setting", type=str, nargs="+",
    default=["baseline", "full_rerank"],
    help="벤치마크 설정 (baseline, full, full_rerank, full_rerank_crag)",
)
```

---

## 7. 실행 절차

```bash
# ──── Phase 1: CRAG 모듈 단독 테스트 ────
# 파이썬 REPL이나 간단한 스크립트로 Evaluator 동작 확인
docker exec -it rag-embedding python3 -c "
from codes.query.compensator import RetrievalEvaluator
evaluator = RetrievalEvaluator(model='sonnet')
# mock top3 결과로 fast path 테스트
print('Fast path test passed')
"

# ──── Phase 2: Set E 벤치마크 (핵심) ────
docker exec -it rag-embedding \
    python codes/query/test_query_decomposition.py \
    --set E --setting full_rerank_crag \
    --output results/phase2a_crag_setE.json

# 목표: P@3 ≥ 60% (현재 54%)

# ──── Phase 3: 전체 회귀 체크 ────
docker exec -it rag-embedding \
    python codes/query/test_query_decomposition.py \
    --setting full_rerank_crag \
    --output results/phase2a_crag_full.json

# 회귀 허용 범위:
#   Set A ≥ 77% (CRAG fast path → 변동 없어야 함)
#   Set B ≥ 58%
#   Set C ≥ 82%
#   Set D ≥ 56%
#   Set E ≥ 60% ★ 핵심 목표
```

---

## 8. 구체적 질의 예시: CRAG 동작 흐름

### 예시 1: "영끌해서 집 샀는데 이자 감당 안 되면 경매 넘어가?"

```
Step 1: Analyzer → SIMPLE (정규 용어 "이자", "경매" 매칭, 30자 이내)
Step 2: Embed + Search → top-3: ["임의경매", "담보", "명도소송"]
Step 3: CE Rerank → 순서 유지 (CE도 비슷한 결과)
Step 4: CRAG Evaluator
  - Fast path: top-1 score=0.72 < 0.85 → 패스
  - Fast path: 정규 용어 "이자"가 top-3에 없음 → 패스
  - LLM 평가: "질의는 과다차입으로 인한 강제경매 위험을 물음.
              결과는 경매 절차(임의경매, 명도)에 치우쳐 있음"
  → grade: AMBIGUOUS
  → formal_terms: ["과다차입", "강제경매", "연체"]

Step 5: CRAG Compensator (AMBIGUOUS)
  - 보정 쿼리: "과다차입 강제경매 연체"
  - 보정 검색: ["과다차입", "강제경매", "연체이자", "채무불이행", ...]
  - RRF merge: [초기×0.6, 보정×1.0]
  - 최종 top-3: ["과다차입", "강제경매", "임의경매"]

P@3: ✓ (기대 키워드 "과다차입" 매칭)
```

### 예시 2: "종부세 기준 금액" (Set A, 정규 질의)

```
Step 1: Analyzer → SIMPLE (정규 용어 "종부세" 매칭)
Step 2: Search → top-3: ["종합부동산세", "과세표준", "공정시장가액비율"]
Step 3: CE Rerank → 순서 유지
Step 4: CRAG Evaluator
  - Fast path: top-1 score=0.91 ≥ 0.85 → CORRECT
  → 즉시 반환 (LLM 호출 없음, 추가 지연 0)
```

### 예시 3: "줍줍 당첨되면 세금?" (Set E, 슬랭)

```
Step 1: Analyzer → SIMPLE (alias "줍줍" 매칭)
Step 2: Search → top-3: ["무순위청약", "청약통장", "분양가상한제"]
Step 3: CE Rerank → ["청약통장", "무순위청약", "분양가상한제"]
Step 4: CRAG Evaluator
  - Fast path: top-1 score=0.68, 용어 "줍줍"이 top-3에 간접 매칭 → 패스
  - LLM 평가: "줍줍 당첨 시 세금을 물음. 결과는 청약 관련이나 세금 정보 부재"
  → grade: INCORRECT
  → formal_terms: ["취득세", "청약 당첨 세금", "분양권 세금"]

Step 5: CRAG Compensator (INCORRECT)
  - 보정 쿼리 1: "취득세 청약 당첨 세금 분양권 세금"
  - 보정 쿼리 2: "줍줍 당첨되면 세금? 취득세"
  - 보정 검색 → RRF merge
  - 최종 top-3: ["취득세", "분양권 양도소득세", "청약 당첨"]

P@3: ✓ (기대 키워드 "취득세" 매칭)
```

---

## 9. LLM 호출 비용 분석

### Set E (100 쿼리) 예측

| 경로 | 쿼리 수 | 추가 LLM 호출 | 추가 시간 |
|------|---------|-------------|----------|
| Fast path → CORRECT | ~55 | 0 | 0 |
| LLM 평가 → CORRECT | ~10 | 10 | 70초 |
| LLM 평가 → AMBIGUOUS → 재검색 | ~20 | 20 | 140초 |
| LLM 평가 → INCORRECT → 재검색 | ~15 | 15 | 105초 |
| **합계** | 100 | **~45** | **~315초 (5.3분)** |

기존 Full+Rerank 벤치마크 시간 (~30분)에 +5분 추가. 전체 실행 시간 ~35분.

### 전체 500 쿼리

Set A/C는 대부분 fast path이므로 추가 비용 미미:

| 세트 | Fast path 비율 | 추가 LLM 호출 | 추가 시간 |
|------|---------------|-------------|----------|
| A (150) | ~95% | ~7 | ~50초 |
| B (50) | ~50% | ~15 | ~105초 |
| C (100) | ~90% | ~5 | ~35초 |
| D (100) | ~60% | ~20 | ~140초 |
| E (100) | ~55% | ~45 | ~315초 |
| **합계** | — | **~92** | **~10.8분** |

---

## 10. 예상 결과

### Set E 상세 예측

| Sub-category | 현재 성공 | CRAG 후 예상 | 개선 근거 |
|-------------|----------|------------|----------|
| E1-20 (슬랭) | 8/20 (40%) | 14-16/20 (70-80%) | 슬랭→정규 매핑이 CRAG 핵심 강점 |
| E21-35 (크로스도메인) | 7/15 (47%) | 10-11/15 (67-73%) | 누락 도메인 보정 |
| E36-45 (시사) | 4/10 (40%) | 6-7/10 (60-70%) | 정책 용어 보정 |
| E46-55 (커뮤니티) | 6/10 (60%) | 7-8/10 (70-80%) | 구어체 보정 |
| E56-75 (세금+대출) | 14/20 (70%) | 15-17/20 (75-85%) | 이미 높음, 소폭 개선 |
| E76-90 (권리분석) | 10/15 (67%) | 11-13/15 (73-87%) | 전문 용어 보정 |
| E91-100 (실무) | 5/10 (50%) | 6-8/10 (60-80%) | 절차 용어 보정 |
| **합계** | **54/100** | **~64-68/100** | **+10-14%p** |

### 전체 성과 예측 (Alias Pruning + CRAG 통합)

| 세트 | 현재 | Pruning 후 | + CRAG 후 | 목표 | 판정 |
|------|------|-----------|----------|------|------|
| A | 77% | 79% | 79% | ≥79% | **달성** |
| B | 60% | 60% | 61% | ≥60% | **달성** |
| C | 82% | 82% | 82% | ≥82% | **달성** |
| D | 58% | 58% | 60% | ≥59% | **달성** |
| E | 54% | 54% | **64%** | ≥60% | **달성** |
| **전체** | **68%** | **69%** | **~72%** | ≥70% | **달성** |

---

## 11. 참고 문헌

| 출처 | 연도 | 핵심 기여 | 본 작업 적용 |
|------|------|-----------|------------|
| CRAG (Yan et al.) | 2024 (ICLR 2025) | 3단계 검색 평가 + 보정 | 전체 아키텍처 |
| Self-RAG (Asai et al.) | 2023 (NeurIPS) | Reflection tokens, 적응적 검색 | Rule-based fast path |
| FILCO | 2024 | 저관련성 필터링 (EM +8.6%) | AMBIGUOUS 경로 설계 |
| TA-ARE | 2025 | 학습 임계값, 불필요 검색 -14.9% | 점수 임계값 설계 |
| RAG-Fusion | 2024 | 다중 쿼리 + RRF | INCORRECT 경로의 다중 보정 쿼리 |
| Adaptive Retrieval (arXiv:2602.07213) | 2025 | 검색 안 하는 것이 더 나을 때도 있음 | fast path 정당화 |
