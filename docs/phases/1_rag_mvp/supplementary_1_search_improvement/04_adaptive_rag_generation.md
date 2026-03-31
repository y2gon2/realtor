# Sprint 3: Adaptive RAG Generation Layer — LangGraph 상태 머신 설계

> 목적: LLM 답변 생성 레이어를 LangGraph 기반 상태 머신으로 구현. 검색 → 평가 → 생성 → 검증의 자동 루프
> 생성 파일: `codes/generation/graph.py`, `codes/generation/nodes.py`, `codes/generation/prompts.py`, `codes/generation/state.py`

> **Phase 2 종합 평가 결론**: 검색 파이프라인 최적화는 P@3 68.0%에서 한계에 도달.
> 정규 질의 80%는 프로덕션급이나, 구어체 57%는 검색만으로 해결 불가.
> **답변 생성 레이어(이 Sprint)가 나머지 7%p 격차를 메우는 핵심 전략.**
> (Phase 2 `7_phase2_comprehensive_evaluation.md` Section 5.3 "검색 최적화 중단 기준" 참조)

---

## 0. 왜 LangGraph인가?

### 단순 체이닝 vs 상태 머신

```
[단순 체이닝 — 현재 불가능한 이유]
질의 → 검색 → LLM 생성 → 답변

문제: 검색 결과가 부적합해도 무조건 답변 생성
문제: 답변에 hallucination이 있어도 감지 불가
문제: 복잡한 질의는 한 번의 검색으로 부족
```

```
[상태 머신 — Adaptive RAG]
질의 → 검색 → 문서평가 ──(불합격)──→ 질의재작성 → 검색 (루프)
                │
           (합격)
                ▼
          LLM 생성 → 환각검사 ──(환각)──→ 질의재작성 → 검색 (루프)
                          │
                     (합격)
                          ▼
                        답변
```

> **핵심 개념 — LangGraph란?**
>
> LangChain 팀이 만든 Python 프레임워크로, LLM 기반 애플리케이션을 **그래프(노드 + 엣지)**로 설계할 수 있다.
>
> - **노드(Node)**: 하나의 작업 단위 (예: "검색", "생성", "평가")
> - **엣지(Edge)**: 노드 간 연결. **조건부 엣지**는 "평가 결과가 합격이면 생성으로, 불합격이면 재검색으로" 같은 분기를 표현
> - **상태(State)**: 그래프 실행 중 공유되는 데이터 (질의, 검색 결과, 생성된 답변 등)
>
> **비유**: 회사의 결재 프로세스와 같다. 문서가 각 부서(노드)를 거치며, 각 부서에서 "승인(다음 부서로)" 또는 "반려(이전 부서로 되돌림)"를 결정한다.
>
> 설치: `pip install langgraph`

> **Phase 2 종합 평가의 제안 아키텍처와의 관계**
>
> Phase 2 `7_phase2_comprehensive_evaluation.md` Section 5-4에서 제안된 "Retrieval Confidence Scorer" 아키텍처:
> - 높은 신뢰도 (Top-1 CE ≥ 0.7) → 즉시 답변 생성
> - 중간 신뢰도 (0.3 ≤ CE < 0.7) → 답변 + "참고 수준" 면책
> - 낮은 신뢰도 (CE < 0.3) → LLM 확장 질의 → 재검색
>
> 이 아키텍처를 LangGraph 상태 머신의 `grade_documents` 노드에 통합한다.

---

## 1. 전체 아키텍처

### 1-1. 그래프 구조

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │
                           ▼
                ┌──────────────────┐
                │  analyze_query   │  ← 기존 QueryAnalyzer
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │    retrieve      │  ← 기존 SearchPipeline
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐        ┌──────────────────┐
                │  grade_documents │──(FAIL)─►│  rewrite_query   │
                └────────┬─────────┘        └────────┬─────────┘
                         │ (PASS)                    │
                         ▼                           │ (재검색)
                ┌──────────────────┐                 │
                │    generate      │◄────────────────┘
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐        ┌──────────────────┐
                │  check_halluc.   │──(FAIL)─►│  rewrite_query   │
                └────────┬─────────┘        └──────────────────┘
                         │ (PASS)
                         ▼
                ┌──────────────────┐
                │     END          │
                └──────────────────┘
```

### 1-2. 상태 정의 — `state.py`

```python
"""Adaptive RAG 상태 머신의 공유 상태."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class RAGState:
    """그래프 실행 중 공유되는 상태.

    LangGraph에서 각 노드는 이 상태를 읽고 수정한다.
    노드 함수의 인자로 전달되고, 반환값으로 상태를 업데이트한다.
    """
    # 입력
    original_query: str = ""

    # 질의 분석
    analysis_type: str = ""                  # SIMPLE / REWRITE / DECOMPOSE
    search_queries: list[str] = field(default_factory=list)

    # 검색 결과
    ontology_results: list = field(default_factory=list)
    legal_results: list = field(default_factory=list)
    parent_documents: list = field(default_factory=list)

    # 문서 평가
    doc_grade: Literal["pass", "fail"] = ""
    grade_reason: str = ""

    # 생성
    generated_answer: str = ""
    citations: list[dict] = field(default_factory=list)

    # 환각 검사
    hallucination_check: Literal["pass", "fail"] = ""
    hallucination_reason: str = ""

    # 루프 제어
    retry_count: int = 0
    max_retries: int = 2                     # 최대 재시도 횟수

    # 메타
    total_latency_ms: float = 0.0
    llm_calls: int = 0
```

> **`@dataclass`란?**
>
> Python의 데이터 클래스 데코레이터. `__init__`, `__repr__` 등을 자동 생성해준다.
>
> ```python
> @dataclass
> class Point:
>     x: float = 0
>     y: float = 0
>
> p = Point(x=3, y=4)  # __init__ 자동 생성
> print(p)              # Point(x=3, y=4) — __repr__ 자동 생성
> ```

---

## 2. 노드 구현 — `nodes.py`

### 2-1. analyze_query 노드

```python
"""Adaptive RAG 그래프의 각 노드 함수."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embedding"))

from analyzer import QueryAnalyzer
from pipeline import SearchPipeline
from state import RAGState


# 싱글톤 인스턴스 (그래프 실행 중 재사용)
_analyzer: QueryAnalyzer | None = None
_pipeline: SearchPipeline | None = None


def _get_analyzer() -> QueryAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryAnalyzer()
    return _analyzer


def _get_pipeline() -> SearchPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SearchPipeline()
    return _pipeline


def analyze_query(state: RAGState) -> dict:
    """노드 1: 질의 분석 (기존 QueryAnalyzer 재사용).

    기존 2단계 게이팅(Tier 1 룰 + Tier 2 LLM)을 그대로 호출.
    """
    analyzer = _get_analyzer()
    analysis = analyzer.analyze(state.original_query)

    queries = [state.original_query]  # 원본 항상 포함
    for sq in analysis.queries:
        if sq.query != state.original_query:
            queries.append(sq.query)

    return {
        "analysis_type": analysis.type,
        "search_queries": queries,
        "llm_calls": state.llm_calls + (1 if analysis.llm_called else 0),
    }
```

### 2-2. retrieve 노드

```python
def retrieve(state: RAGState) -> dict:
    """노드 2: 검색 (기존 SearchPipeline 재사용 + Parent Doc).

    Sprint 1에서 추가된 HyDE, RAG-Fusion, Parent Document Retrieval 포함.
    """
    pipeline = _get_pipeline()
    t0 = time.time()

    # realestate_v2 검색 (KURE-v1, 현재 93,943→재색인 후 ~151K 청크)
    # + domain_ontology_v2 + legal_docs_v2 검색 (BGE-M3)
    result = pipeline.search(
        state.original_query,
        limit=5,
        rerank=True,
        crag=True,              # Phase 2에서 이미 구현 (compensator.py)
        fetch_parents=True,     # Sprint 1 Parent Doc (신규)
        # 주의: realestate_v2 재색인 후 Parent Doc의 범위가 확대됨
        # 11,035 문서의 summary + atomic_facts를 모두 활용 가능
    )

    latency = (time.time() - t0) * 1000

    return {
        "ontology_results": result.ontology_results,
        "legal_results": result.legal_results,
        "parent_documents": result.parent_documents,
        "total_latency_ms": state.total_latency_ms + latency,
    }
```

### 2-3. grade_documents 노드

```python
GRADE_PROMPT = """다음 검색 결과가 사용자 질문에 답하기에 충분한지 평가하세요.

## 질문
{query}

## 검색 결과
{context}

## 평가 기준
- 질문의 핵심 주제에 대한 정보가 포함되어 있는가?
- 구체적인 수치, 조건, 절차 등이 있는가?
- 검색 결과만으로 정확한 답변을 생성할 수 있는가?

"pass" 또는 "fail"로만 답하세요. 이유를 한 줄로 덧붙이세요.
형식: pass|이유 또는 fail|이유"""


def grade_documents(state: RAGState) -> dict:
    """노드 3: 검색 결과의 관련성 평가.

    Phase 2의 CRAG(compensator.py)가 이미 CORRECT/AMBIGUOUS/INCORRECT를
    판정하므로, 여기서는 LLM 수준의 추가 평가를 수행한다.

    판정 기준 (Phase 2 종합 평가 Section 5-4 반영):
    - CRAG grade가 CORRECT + top-1 score ≥ 0.7 → 자동 pass
    - CRAG grade가 AMBIGUOUS → LLM 평가 실행
    - CRAG grade가 INCORRECT → fail (재검색)
    """
    if not state.ontology_results and not state.legal_results:
        return {
            "doc_grade": "fail",
            "grade_reason": "검색 결과 없음",
            "llm_calls": state.llm_calls + 1,
        }

    # 검색 결과를 텍스트로 포맷
    context_parts = []
    for i, point in enumerate(state.ontology_results[:5]):
        term = point.payload.get("term", "")
        desc = point.payload.get("description", "")[:200]
        context_parts.append(f"[{i+1}] {term}: {desc}")

    for i, point in enumerate(state.legal_results[:3]):
        section = point.payload.get("section_title", "")
        text = point.payload.get("text", "")[:200]
        context_parts.append(f"[법률 {i+1}] {section}: {text}")

    context = "\n".join(context_parts)

    prompt = GRADE_PROMPT.format(
        query=state.original_query,
        context=context,
    )

    analyzer = _get_analyzer()
    try:
        response = analyzer._call_claude_cli(prompt)
        parts = response.strip().split("|", 1)
        grade = parts[0].strip().lower()
        reason = parts[1].strip() if len(parts) > 1 else ""

        return {
            "doc_grade": "pass" if "pass" in grade else "fail",
            "grade_reason": reason,
            "llm_calls": state.llm_calls + 1,
        }
    except Exception as e:
        # 평가 실패 시 보수적으로 pass (검색 결과를 신뢰)
        return {
            "doc_grade": "pass",
            "grade_reason": f"평가 실패 (fallback pass): {e}",
            "llm_calls": state.llm_calls + 1,
        }
```

### 2-4. generate 노드

```python
GENERATE_PROMPT = """당신은 대한민국 부동산 전문 상담사입니다.

아래 검색 결과를 기반으로 사용자 질문에 정확하게 답변하세요.

## 답변 규칙
1. **검색 결과에 있는 정보만** 사용하세요. 없는 내용을 추가하지 마세요.
2. 구체적인 수치(세율, 금액, 기간)가 있으면 반드시 포함하세요.
3. 출처를 [1], [2] 형태로 인용하세요.
4. 확실하지 않은 내용은 "정확한 내용은 세무사/법률 전문가와 상담하세요"로 안내하세요.
5. 한국어로 자연스럽게, 존댓말로 답변하세요.

## 사용자 질문
{query}

## 검색 결과
{context}

## 답변"""


def generate(state: RAGState) -> dict:
    """노드 4: LLM 답변 생성 (출처 인용 포함).

    Parent Document가 있으면 풍부한 컨텍스트로 생성,
    없으면 검색 결과의 payload 텍스트로 생성.
    """
    # 컨텍스트 조립: Parent Document 우선, 없으면 검색 결과 payload
    context_parts = []

    if state.parent_documents:
        # Parent Document 사용 (Sprint 1)
        for i, doc in enumerate(state.parent_documents):
            context_parts.append(f"[{i+1}] 문서: {doc['doc_id']}")
            if doc.get("summary"):
                context_parts.append(f"  요약: {doc['summary']}")
            for j, fact in enumerate(doc.get("facts", [])[:10]):
                context_parts.append(f"  - {fact}")
            context_parts.append("")
    else:
        # 검색 결과 직접 사용
        for i, point in enumerate(state.ontology_results[:5]):
            term = point.payload.get("term", "")
            desc = point.payload.get("description", "")
            context_parts.append(f"[{i+1}] {term}")
            context_parts.append(f"  {desc[:300]}")
            context_parts.append("")

    # 법률 결과 추가
    for i, point in enumerate(state.legal_results[:3]):
        section = point.payload.get("section_title", "")
        text = point.payload.get("text", "")[:300]
        idx = len(state.ontology_results) + i + 1
        context_parts.append(f"[{idx}] {section}")
        context_parts.append(f"  {text}")
        context_parts.append("")

    context = "\n".join(context_parts)

    prompt = GENERATE_PROMPT.format(
        query=state.original_query,
        context=context,
    )

    analyzer = _get_analyzer()
    try:
        answer = analyzer._call_claude_cli(prompt)

        # 인용 번호 추출 (간단한 정규식)
        import re
        citation_nums = set(int(n) for n in re.findall(r'\[(\d+)\]', answer))
        citations = []
        for num in sorted(citation_nums):
            if num <= len(state.ontology_results):
                point = state.ontology_results[num - 1]
                citations.append({
                    "index": num,
                    "term": point.payload.get("term", ""),
                    "source": point.payload.get("channel", ""),
                })

        return {
            "generated_answer": answer.strip(),
            "citations": citations,
            "llm_calls": state.llm_calls + 1,
        }
    except Exception as e:
        return {
            "generated_answer": f"답변 생성 중 오류가 발생했습니다: {e}",
            "citations": [],
            "llm_calls": state.llm_calls + 1,
        }
```

### 2-5. check_hallucination 노드

```python
HALLUCINATION_CHECK_PROMPT = """다음 답변이 제공된 검색 결과에 근거하는지 확인하세요.

## 검색 결과 (근거 자료)
{context}

## 생성된 답변
{answer}

## 확인 기준
- 답변의 모든 구체적 수치(세율, 금액, 기간)가 검색 결과에 있는가?
- 검색 결과에 없는 조건이나 예외가 추가되지 않았는가?
- 인용 번호 [1], [2]가 실제 해당 검색 결과를 참조하는가?

"pass" (근거 있음) 또는 "fail" (환각 감지)로만 답하세요. 이유를 한 줄로.
형식: pass|이유 또는 fail|환각 내용"""


def check_hallucination(state: RAGState) -> dict:
    """노드 5: 환각 검사 — 답변이 검색 결과에 근거하는지 확인.

    Faithfulness 메트릭의 실시간 버전.
    RAGAS의 Faithfulness와 동일한 개념이지만,
    여기서는 답변 생성 직후에 실시간으로 검사한다.
    """
    # 간단한 컨텍스트 재조립
    context_parts = []
    for i, point in enumerate(state.ontology_results[:5]):
        term = point.payload.get("term", "")
        desc = point.payload.get("description", "")[:300]
        context_parts.append(f"[{i+1}] {term}: {desc}")

    context = "\n".join(context_parts)

    prompt = HALLUCINATION_CHECK_PROMPT.format(
        context=context,
        answer=state.generated_answer,
    )

    analyzer = _get_analyzer()
    try:
        response = analyzer._call_claude_cli(prompt)
        parts = response.strip().split("|", 1)
        check = parts[0].strip().lower()
        reason = parts[1].strip() if len(parts) > 1 else ""

        return {
            "hallucination_check": "pass" if "pass" in check else "fail",
            "hallucination_reason": reason,
            "llm_calls": state.llm_calls + 1,
        }
    except Exception:
        return {
            "hallucination_check": "pass",  # 보수적 fallback
            "hallucination_reason": "검사 실패 (fallback pass)",
            "llm_calls": state.llm_calls + 1,
        }
```

### 2-6. rewrite_query 노드

```python
def rewrite_query(state: RAGState) -> dict:
    """노드 6: 질의 재작성 (문서 평가/환각 검사 실패 시).

    기존 QueryAnalyzer의 REWRITE 경로를 강제 실행.
    실패 이유를 참고하여 더 구체적인 질의를 생성.
    """
    if state.retry_count >= state.max_retries:
        # 재시도 한계 초과 → 현재 결과로 강제 진행
        return {
            "doc_grade": "pass",  # 강제 통과
            "grade_reason": f"재시도 한계 초과 ({state.max_retries}회)",
        }

    # 실패 이유를 포함한 재작성 프롬프트
    reason = state.grade_reason or state.hallucination_reason

    rewrite_prompt = f"""원래 질문: {state.original_query}
실패 이유: {reason}

위 질문을 더 구체적으로 재작성하세요. 관련 전문용어를 포함하세요.
재작성된 질문만 반환하세요."""

    analyzer = _get_analyzer()
    try:
        rewritten = analyzer._call_claude_cli(rewrite_prompt)
        return {
            "search_queries": [state.original_query, rewritten.strip()],
            "retry_count": state.retry_count + 1,
            "llm_calls": state.llm_calls + 1,
        }
    except Exception:
        return {
            "retry_count": state.retry_count + 1,
            "llm_calls": state.llm_calls + 1,
        }
```

---

## 3. 그래프 조립 — `graph.py`

```python
"""Adaptive RAG — LangGraph 상태 머신 조립 및 실행."""

from langgraph.graph import StateGraph, END
from state import RAGState
from nodes import (
    analyze_query,
    retrieve,
    grade_documents,
    generate,
    check_hallucination,
    rewrite_query,
)


def should_generate_or_rewrite(state: RAGState) -> str:
    """조건부 엣지: 문서 평가 결과에 따라 분기.

    pass → generate (답변 생성)
    fail → rewrite_query (질의 재작성 후 재검색)
    """
    if state.doc_grade == "pass":
        return "generate"
    return "rewrite_query"


def should_end_or_rewrite(state: RAGState) -> str:
    """조건부 엣지: 환각 검사 결과에 따라 분기.

    pass → END (답변 반환)
    fail → rewrite_query (재시도)
    """
    if state.hallucination_check == "pass":
        return END
    return "rewrite_query"


def build_graph() -> StateGraph:
    """Adaptive RAG 그래프 빌드.

    노드 구성:
    1. analyze_query — 질의 분석 (QueryAnalyzer)
    2. retrieve      — 검색 (SearchPipeline + HyDE + RAG-Fusion + CRAG)
    3. grade_docs    — 문서 관련성 평가
    4. generate      — LLM 답변 생성
    5. check_halluc  — 환각 검사
    6. rewrite       — 질의 재작성 (실패 시)

    엣지:
    - analyze → retrieve → grade_docs
    - grade_docs → (pass) → generate → check_halluc → (pass) → END
    - grade_docs → (fail) → rewrite → retrieve (루프)
    - check_halluc → (fail) → rewrite → retrieve (루프)
    """
    graph = StateGraph(RAGState)

    # 노드 추가
    graph.add_node("analyze_query", analyze_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_documents", grade_documents)
    graph.add_node("generate", generate)
    graph.add_node("check_hallucination", check_hallucination)
    graph.add_node("rewrite_query", rewrite_query)

    # 엣지 연결
    graph.set_entry_point("analyze_query")
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "grade_documents")

    # 조건부 엣지: 문서 평가 → 생성 or 재작성
    graph.add_conditional_edges(
        "grade_documents",
        should_generate_or_rewrite,
        {
            "generate": "generate",
            "rewrite_query": "rewrite_query",
        }
    )

    graph.add_edge("generate", "check_hallucination")

    # 조건부 엣지: 환각 검사 → 종료 or 재작성
    graph.add_conditional_edges(
        "check_hallucination",
        should_end_or_rewrite,
        {
            END: END,
            "rewrite_query": "rewrite_query",
        }
    )

    # 재작성 → 재검색 (루프)
    graph.add_edge("rewrite_query", "retrieve")

    return graph.compile()


# ─────────────────── 실행 인터페이스 ─────────────────────

def ask(query: str) -> dict:
    """Adaptive RAG 질의 실행.

    Args:
        query: 사용자 질문 (자연어)

    Returns:
        {
            "answer": str,          # 생성된 답변
            "citations": list,      # 출처 목록
            "retries": int,         # 재시도 횟수
            "llm_calls": int,       # 총 LLM 호출 수
            "latency_ms": float,    # 총 소요 시간
        }
    """
    app = build_graph()

    initial_state = RAGState(original_query=query)
    final_state = app.invoke(initial_state)

    return {
        "answer": final_state.get("generated_answer", ""),
        "citations": final_state.get("citations", []),
        "retries": final_state.get("retry_count", 0),
        "llm_calls": final_state.get("llm_calls", 0),
        "latency_ms": final_state.get("total_latency_ms", 0),
    }


# ─────────────────── CLI ─────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "경매 낙찰되면 세금 내야해?"

    print(f"질의: {query}")
    print("=" * 70)

    result = ask(query)

    print(f"\n답변:\n{result['answer']}")
    print(f"\n출처: {result['citations']}")
    print(f"재시도: {result['retries']}회 | LLM: {result['llm_calls']}회 | "
          f"소요: {result['latency_ms']:.0f}ms")
```

---

## 4. 실행 흐름 예시

### 4-1. 정상 흐름 (재시도 없음)

```
질의: "1주택자 양도세 비과세 조건"

[analyze_query] type=SIMPLE, 매칭 용어: [양도세, 비과세, 1주택]
[retrieve] 5개 결과, Parent Doc 3개, 350ms
[grade_documents] pass — "양도세 비과세 조건이 검색 결과에 포함"
[generate] "1세대 1주택자의 양도소득세 비과세 조건은..." [1][2]
[check_hallucination] pass — "세율, 기간 모두 검색 결과에 근거"
→ 답변 반환 (LLM 3회, 재시도 0회)
```

### 4-2. 재시도 흐름 (문서 평가 실패)

```
질의: "부동산 사면 나라에 돈 내야 되나" (극단 구어체, Set B 유형)

※ Phase 2 기준: Set B(구어체) P@3 = 60% (CRAG + CE bypass 적용 후)
   검색만으로 57%→60% 개선했으나, 이 질의처럼 여전히 실패하는 40%가 존재.
   → 생성 레이어의 재시도 루프가 이 격차를 보상.

[analyze_query] type=REWRITE, 변환: "부동산 취득세 납부 의무"
[retrieve] 5개 결과, 1개만 관련 (경매 절차가 상위), 450ms
[grade_documents] CRAG=AMBIGUOUS → LLM 평가 실행 → fail — "취득세 관련 결과가 1개뿐, 불충분"
[rewrite_query] "부동산 취득 시 납부해야 하는 세금 종류와 세율"
[retrieve] 5개 결과, 4개 관련 (취득세 상위), 400ms
[grade_documents] CRAG=CORRECT, top-1 CE=0.82 → 자동 pass
[generate] "부동산을 구입하면 취득세를 납부해야 합니다..." [1][2][3]
[check_hallucination] pass
→ 답변 반환 (LLM 4회, 재시도 1회) — CE bypass로 LLM 1회 절약
```

---

## 5. 실행 순서

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **1** | `codes/generation/` 디렉토리 생성 | — |
| **2** | `state.py` 작성 (RAGState dataclass) | — |
| **3** | `nodes.py` 작성 (6개 노드 함수) | Sprint 1, 2 완료 |
| **4** | `graph.py` 작성 (그래프 조립 + CLI) | 2, 3 |
| **5** | `langgraph` 패키지 설치 | — |
| **6** | 10개 질의 수동 테스트 | 4, 5 |
| **7** | 프롬프트 튜닝 (grade, generate, hallucination check) | 6 |
| **8** | Docker 컨테이너에 langgraph 추가 | 5 |

---

## 6. 위험 요소

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| 무한 루프 (grade 계속 fail) | 중 | 시스템 정지 | `max_retries=2`로 제한, 초과 시 강제 통과 |
| LLM 호출 과다 (비용) | 중 | 질의당 ~$0.02 | 단순 질의는 grade 스킵 (SIMPLE 타입) |
| 기존 CRAG와 중복 | 저 | 불필요한 재평가 | grade_documents가 CRAG grade를 먼저 확인하여 CORRECT면 스킵 |
| 환각 검사 오탐 | 중 | 정상 답변 재시도 | 보수적 프롬프트 + fallback pass |
| LangGraph 의존성 | 저 | 패키지 업데이트 불일치 | 버전 고정 (`langgraph==0.x.x`) |
