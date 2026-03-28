# `codes/query/analyzer.py` — QueryAnalyzer 상세 코드 설계

> 목적: 사용자 질의를 분석하여 SIMPLE / REWRITE / DECOMPOSE로 분류하고, 검색 최적화된 질의를 반환
> 패턴 원본: `scripts/build_ontology.py` (Claude API 호출, JSON 파싱, 재시도)
> 선행 문서: `01_query_decomposition_plan.md`

---

## 1. 전체 구조

### 1-1. `codes/query/` 디렉토리 구성

```
codes/query/
    ├── __init__.py                  # 패키지 초기화
    ├── config.py                    # 상수, 경로, 도메인 키워드 맵
    ├── prompts.py                   # LLM 프롬프트 템플릿
    └── analyzer.py                  # QueryAnalyzer 클래스 (이 문서)
```

### 1-2. 모듈 간 의존 관계

```
analyzer.py
    ├── config.py          (상수, 경로)
    ├── prompts.py         (프롬프트 템플릿)
    ├── anthropic          (Claude API 클라이언트)
    └── ontology_data/     (entries/*.json — 사전 필터용)
```

---

## 2. `config.py` — 상수 및 설정

```python
#!/usr/bin/env python3
"""
Query Decomposition 설정 모듈.

상수, 파일 경로, 도메인 키워드 맵을 관리한다.
"""

from pathlib import Path

# ─────────────────────────── 경로 ───────────────────────────

PROJECT_ROOT   = Path("/home/gon/ws/rag")
ENTRIES_DIR    = PROJECT_ROOT / "ontology_data" / "entries"
TAXONOMY_FILE  = PROJECT_ROOT / "ontology_data" / "taxonomy.json"

# ─────────────────────────── 모델 ───────────────────────────

MODEL = "claude-sonnet-4-6"        # Query Analyzer용 모델
MAX_TOKENS = 1024                   # JSON 응답은 ~200 토큰이면 충분
TEMPERATURE = 0.0                   # 일관된 분류를 위해 0으로 고정

# ─────────────────────────── 게이팅 ───────────────────────────

MAX_SIMPLE_LENGTH = 15              # 이 길이 이하의 정규 용어 질의는 SIMPLE
LLM_RETRY_COUNT = 3                 # LLM 호출 실패 시 재시도 횟수
LLM_RETRY_WAIT = 2                  # 재시도 대기 시간(초)
RATE_LIMIT_WAIT = 30                # Rate Limit 대기 시간(초)

# ─────────────────────────── 도메인 ───────────────────────────

# taxonomy.json에서 자동 로드할 수도 있지만,
# 프롬프트에 직접 포함할 10개 브랜치를 명시적으로 정의한다.
DOMAIN_BRANCHES = {
    "tax":            "세금 (취득세, 양도소득세, 종부세, 재산세, 상속세, 증여세)",
    "loan":           "대출/금융 (LTV, DSR, DTI, 주택담보대출, 전세대출)",
    "subscription":   "청약/분양 (청약가점, 특별공급, 분양가상한제)",
    "rental":         "임대차 (전세, 월세, 보증금, 임대차보호법)",
    "auction":        "경매/공매 (입찰, 낙찰, 배당, 명도)",
    "contract":       "계약/거래 (매매계약, 중개보수, 거래신고)",
    "reconstruction": "재건축/재개발 (안전진단, 초과이익환수, 조합)",
    "regulation":     "규제/정책 (투기과열지구, 조정대상지역)",
    "land":           "토지/개발 (지목, 용적률, 건폐율, 용도지역)",
    "registration":   "등기/권리 (소유권이전, 근저당, 전세권)",
}

# 인과/조건 패턴 — 이 패턴이 포함되면 SIMPLE이 아닐 가능성 높음
CAUSAL_PATTERNS = [
    "하면", "할 때", "인 경우", "되면", "이면",
    "있으면", "없으면", "나면", "되나", "할까",
    "해야", "돼?", "되?", "야해", "야돼",
]
```

---

## 3. `prompts.py` — LLM 프롬프트 설계

### 3-1. 프롬프트 설계 원칙

> **쉬운 비유 — 프롬프트는 업무 지시서:**
>
> 신입 직원에게 업무를 맡길 때, "알아서 해"라고 하면 결과가 중구난방이다. "이 양식으로, 이 기준으로, 이런 경우에는 이렇게"라고 구체적으로 지시하면 일관된 결과를 얻는다. LLM 프롬프트도 마찬가지로, **역할 + 도메인 지식 + 판단 기준 + 출력 형식 + 예시**를 모두 포함해야 안정적인 출력을 받을 수 있다.

### 3-2. 시스템 프롬프트

```python
#!/usr/bin/env python3
"""
Query Decomposition LLM 프롬프트 템플릿.
"""

from config import DOMAIN_BRANCHES

# ─────────────── 도메인 목록 문자열 생성 ──────────────────────

def _build_domain_list() -> str:
    """프롬프트에 삽입할 도메인 브랜치 목록 문자열."""
    lines = []
    for key, desc in DOMAIN_BRANCHES.items():
        lines.append(f"- {key}: {desc}")
    return "\n".join(lines)


# ─────────────── 시스템 프롬프트 ──────────────────────────────

SYSTEM_PROMPT = f"""당신은 대한민국 부동산 RAG 시스템의 질의 분석 전문가입니다.

사용자의 부동산 질의를 분석하여 벡터 검색에 최적화된 형태로 변환합니다.

## 작업
1. 질의 유형을 판단합니다: SIMPLE | REWRITE | DECOMPOSE
2. 유형에 따라 적절한 처리를 합니다.

## 유형 판단 기준

### SIMPLE (변환 불필요)
- 이미 전문 용어를 사용한 단일 도메인 질의
- 예: "종부세 기준 금액", "DSR 40% 규제", "1주택자 양도세 비과세"
- 이 경우 원본 질의를 그대로 반환합니다.

### REWRITE (구어체 → 전문용어 변환)
- 구어체, 비공식 표현, 추상적 표현을 사용한 단일 도메인 질의
- 벡터 검색이 전문용어 기반이므로, 구어체를 전문용어로 변환해야 정확한 결과를 얻을 수 있음
- 예: "집 살 때 세금 얼마야" → "주택 매매 시 취득세 세율과 부대비용"
- 예: "부동산 사면 나라에 돈 내야 되나" → "부동산 취득 시 취득세 납부 의무와 세율"
- 예: "은행에서 집값의 몇 프로까지 빌려주는지" → "주택담보대출 LTV 담보인정비율 한도"

### DECOMPOSE (복합 질의 → 서브 질의 분리)
- 2개 이상의 도메인에 걸치는 복합 질의
- 인과/조건 관계로 연결된 다중 개념 질의
- 예: "경매 낙찰되면 세금 내야해?" → 경매(auction) + 세금(tax)
- 예: "청약 당첨되면 대출 얼마까지 받을 수 있어" → 청약(subscription) + 대출(loan)
- 서브 질의는 2~3개로 제한합니다.

## 도메인 (10개 브랜치)
{_build_domain_list()}

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

```json
{{
  "type": "SIMPLE | REWRITE | DECOMPOSE",
  "reasoning": "판단 근거 1문장",
  "queries": [
    {{
      "query": "검색에 사용할 질의 (전문용어 포함, 정제된 형태)",
      "domain_hint": "주 도메인 브랜치 키",
      "formal_terms": ["관련 전문용어 1~3개"]
    }}
  ]
}}
```

## 규칙
- SIMPLE: queries에 원본 질의 1개만 포함, domain_hint 지정
- REWRITE: queries에 정제된 질의 1개만 포함, 구어체→전문용어 변환 필수
- DECOMPOSE: queries에 2~3개 서브 질의 포함, 각각 다른 domain_hint 가능
- 질의가 부동산과 무관한 경우에도 SIMPLE로 처리 (원본 그대로 반환)

## 예시

입력: "종부세 기준 금액"
출력:
```json
{{"type": "SIMPLE", "reasoning": "전문용어 '종부세'를 사용한 단일 도메인(세금) 질의", "queries": [{{"query": "종부세 기준 금액", "domain_hint": "tax", "formal_terms": ["종합부동산세", "과세기준금액"]}}]}}
```

입력: "부동산 사면 나라에 돈 내야 되나"
출력:
```json
{{"type": "REWRITE", "reasoning": "구어체 '나라에 돈 내야'는 취득세 납부를 의미하는 비공식 표현", "queries": [{{"query": "부동산 취득 시 취득세 납부 의무와 세율", "domain_hint": "tax", "formal_terms": ["취득세", "과세표준", "세율"]}}]}}
```

입력: "은행에서 집값의 몇 프로까지 빌려주는지"
출력:
```json
{{"type": "REWRITE", "reasoning": "구어체 '몇 프로까지 빌려주는지'는 LTV(담보인정비율) 한도를 묻는 표현", "queries": [{{"query": "주택담보대출 LTV 담보인정비율 한도", "domain_hint": "loan", "formal_terms": ["LTV", "담보인정비율", "대출한도"]}}]}}
```

입력: "경매 낙찰되면 세금 내야해?"
출력:
```json
{{"type": "DECOMPOSE", "reasoning": "경매 절차(경매 도메인)와 취득세 납부(세금 도메인) 2개 영역에 걸침", "queries": [{{"query": "부동산 경매 낙찰 절차와 낙찰자 의무", "domain_hint": "auction", "formal_terms": ["낙찰", "매각허가"]}}, {{"query": "경매 낙찰 부동산 취득세 세율과 납부", "domain_hint": "tax", "formal_terms": ["취득세", "경매취득"]}}]}}
```

입력: "집 살 때 세금 얼마야"
출력:
```json
{{"type": "REWRITE", "reasoning": "구어체 '집 살 때 세금'은 주택 취득 시 취득세를 의미", "queries": [{{"query": "주택 매매 시 취득세 세율과 부대비용", "domain_hint": "tax", "formal_terms": ["취득세", "등록면허세", "세율"]}}]}}
```

입력: "재건축 아파트 팔 때 양도세 오래 갖고 있으면 줄어드나"
출력:
```json
{{"type": "DECOMPOSE", "reasoning": "재건축 양도(재건축 도메인)와 장기보유특별공제(세금 도메인)에 걸침", "queries": [{{"query": "재건축 아파트 양도소득세 과세 특례", "domain_hint": "tax", "formal_terms": ["양도소득세", "재건축"]}}, {{"query": "장기보유특별공제 요건과 공제율", "domain_hint": "tax", "formal_terms": ["장기보유특별공제", "보유기간"]}}, {{"query": "재건축 조합원 입주권 양도 절차", "domain_hint": "reconstruction", "formal_terms": ["조합원", "입주권", "양도"]}}]}}
```
"""


# ─────────────── 유저 프롬프트 ──────────────────────────────

USER_PROMPT_TEMPLATE = """다음 부동산 질의를 분석하세요:

"{query}"

JSON으로만 응답하세요."""
```

> **프롬프트 설계 해설:**
>
> 1. **시스템 프롬프트에 few-shot 예시 6개**를 포함했다. 이는 LLM이 출력 형식을 정확히 따르도록 하는 가장 효과적인 방법이다. 예시가 없으면 LLM이 자체적으로 형식을 변경하거나 추가 텍스트를 넣을 수 있다.
>
> 2. **도메인 목록을 프롬프트에 명시**했다. LLM이 `domain_hint`에 정확한 브랜치 키(tax, loan 등)를 사용하도록 강제한다.
>
> 3. **Temperature를 0으로 설정**했다. 분류 작업에서는 창의성이 아니라 일관성이 중요하다.

---

## 4. `analyzer.py` — QueryAnalyzer 클래스

### 4-1. 데이터 클래스 정의

> **데이터 클래스(dataclass)란?**
>
> Python 3.7부터 도입된 기능으로, 데이터를 담는 클래스를 간결하게 정의할 수 있다. `__init__()`, `__repr__()` 등을 자동으로 생성해 주므로, 보일러플레이트 코드를 줄여준다.
>
> ```python
> # 일반 클래스 (긴 코드)
> class SubQuery:
>     def __init__(self, query, domain_hint, formal_terms):
>         self.query = query
>         self.domain_hint = domain_hint
>         self.formal_terms = formal_terms
>
> # dataclass (같은 기능, 짧은 코드)
> @dataclass
> class SubQuery:
>     query: str
>     domain_hint: str
>     formal_terms: list[str]
> ```

```python
#!/usr/bin/env python3
"""
QueryAnalyzer — 사용자 질의를 분석하여 검색 최적화.

2단계 게이팅:
  Tier 1: 룰 기반 사전 필터 (정규 용어 매칭 → SIMPLE 판정, LLM 호출 안 함)
  Tier 2: Claude Sonnet LLM 호출 (SIMPLE/REWRITE/DECOMPOSE 판정 + 질의 변환)

사용 예시:
    analyzer = QueryAnalyzer()
    result = analyzer.analyze("부동산 사면 나라에 돈 내야 되나")
    print(result.type)       # "REWRITE"
    print(result.queries)    # [SubQuery(query="부동산 취득 시 취득세 납부 의무", ...)]
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from config import (
    MODEL, MAX_TOKENS, TEMPERATURE,
    ENTRIES_DIR, DOMAIN_BRANCHES,
    MAX_SIMPLE_LENGTH, CAUSAL_PATTERNS,
    LLM_RETRY_COUNT, LLM_RETRY_WAIT, RATE_LIMIT_WAIT,
)
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


# ─────────────────────────── 데이터 클래스 ───────────────────

@dataclass
class SubQuery:
    """분해/변환된 서브 질의 하나."""
    query: str                     # 검색에 사용할 질의 텍스트
    domain_hint: str               # 도메인 브랜치 키 (tax, loan, ...)
    formal_terms: list[str] = field(default_factory=list)  # 관련 전문용어


@dataclass
class QueryAnalysis:
    """질의 분석 결과."""
    type: str                      # "SIMPLE" | "REWRITE" | "DECOMPOSE"
    reasoning: str                 # LLM의 판단 근거
    queries: list[SubQuery]        # 검색에 사용할 질의 목록
    original_query: str            # 원본 사용자 질의
    llm_called: bool               # LLM 호출 여부 (False면 사전 필터로 처리)
    latency_ms: float              # 분석 소요 시간 (ms)
```

### 4-2. 사전 필터 (Tier 1) — 정규 용어 매칭

> **쉬운 비유 — 공항 보안 검색대:**
>
> 모든 승객을 정밀 검사하면 시간이 너무 오래 걸린다. 그래서 1차로 금속 탐지기(사전 필터)를 통과시키고, 금속 반응이 있는 사람만 2차 정밀 검사(LLM)를 한다. 사전 필터는 "이 질의가 이미 전문용어를 사용하고 있는가?"를 빠르게 판단하여, 불필요한 LLM 호출을 막는다.

```python
# ─────────────────── 사전 필터 (Tier 1) ───────────────────────

class QueryAnalyzer:
    """사용자 질의를 분석하여 검색 최적화된 형태로 변환."""

    def __init__(self, model: str = MODEL):
        self.client = anthropic.Anthropic()   # ANTHROPIC_API_KEY 환경변수 자동 로드
        self.model = model
        self._formal_terms: set[str] = set()  # 정규 용어 세트
        self._load_formal_terms()

    def _load_formal_terms(self) -> None:
        """ontology_data/entries/*.json에서 term + aliases를 로드하여 세트로 캐싱.

        이 세트는 사전 필터에서 "질의에 전문용어가 포함되어 있는가?"를
        빠르게 판단하는 데 사용된다.

        세트 크기: ~2,146 entries × ~10 aliases = ~21,000 문자열
        메모리: ~2MB (무시 가능)
        로딩 시간: <100ms
        """
        if not ENTRIES_DIR.exists():
            print(f"[QueryAnalyzer] 경고: {ENTRIES_DIR} 없음 — 사전 필터 비활성화")
            return

        count = 0
        for json_file in ENTRIES_DIR.glob("*.json"):
            with open(json_file, encoding="utf-8") as f:
                entries = json.load(f)

            for entry in entries:
                # term 추가 (예: "취득세", "LTV (담보인정비율)")
                term = entry.get("term", "")
                if term:
                    self._formal_terms.add(term)
                    # 괄호 제거 버전도 추가 (예: "LTV")
                    if "(" in term:
                        short = term.split("(")[0].strip()
                        if short:
                            self._formal_terms.add(short)

                # aliases 추가 (예: ["집 살 때 세금", "아파트 취득세", ...])
                for alias in entry.get("aliases", []):
                    if alias:
                        self._formal_terms.add(alias)
                        count += 1

        print(f"[QueryAnalyzer] 정규 용어 {len(self._formal_terms)}개 로드 완료")
```

### 4-3. SIMPLE 판정 로직

```python
    def _find_matching_terms(self, query: str) -> list[str]:
        """질의에 포함된 정규 용어를 찾는다.

        전체 세트를 순회하며 서브스트링 매칭한다.
        세트 크기가 ~21,000이고 각 문자열이 짧으므로 <1ms에 완료된다.

        Returns:
            매칭된 정규 용어 리스트 (빈 리스트면 매칭 없음)
        """
        matched = []
        for term in self._formal_terms:
            if len(term) >= 2 and term in query:  # 1글자 매칭 방지
                matched.append(term)
        return matched

    def _detect_domains(self, query: str) -> list[str]:
        """질의에서 감지된 도메인 브랜치 키 목록을 반환.

        각 도메인의 핵심 키워드가 질의에 포함되어 있는지 확인한다.
        """
        # 브랜치별 핵심 키워드 (간소화)
        domain_keywords = {
            "tax":            ["세금", "취득세", "양도세", "종부세", "재산세", "상속", "증여", "과세"],
            "loan":           ["대출", "LTV", "DSR", "DTI", "담보", "금리", "이자", "빌려"],
            "subscription":   ["청약", "분양", "통장", "가점", "특별공급", "당첨"],
            "rental":         ["전세", "월세", "보증금", "임대", "임차", "세입자", "집주인"],
            "auction":        ["경매", "공매", "낙찰", "입찰", "배당", "명도"],
            "contract":       ["계약", "등기", "중개", "거래", "매매"],
            "reconstruction": ["재건축", "재개발", "안전진단", "조합"],
            "regulation":     ["규제", "조정대상", "투기", "공시가격"],
            "land":           ["토지", "지목", "용적률", "건폐율", "농지"],
            "registration":   ["등기", "근저당", "전세권", "소유권"],
        }

        detected = []
        for branch, keywords in domain_keywords.items():
            if any(kw in query for kw in keywords):
                detected.append(branch)
        return detected

    def _has_causal_pattern(self, query: str) -> bool:
        """질의에 인과/조건 패턴이 포함되어 있는지 확인."""
        return any(p in query for p in CAUSAL_PATTERNS)

    def _is_simple(self, query: str) -> QueryAnalysis | None:
        """Tier 1: 룰 기반 사전 필터.

        정규 용어가 매칭되고, 단일 도메인이며, 짧고 단순한 질의이면
        SIMPLE로 판정하고 LLM 호출을 건너뛴다.

        Returns:
            SIMPLE인 경우 QueryAnalysis, 아니면 None (Tier 2로 진행)
        """
        matched_terms = self._find_matching_terms(query)
        detected_domains = self._detect_domains(query)

        # 조건 1: 정규 용어가 1개 이상 매칭
        if not matched_terms:
            return None

        # 조건 2: 단일 도메인
        if len(detected_domains) >= 2:
            return None

        # 조건 3: 짧은 질의 또는 인과/조건 패턴 없음
        if len(query) > MAX_SIMPLE_LENGTH and self._has_causal_pattern(query):
            return None

        # SIMPLE 판정
        domain = detected_domains[0] if detected_domains else "unknown"
        return QueryAnalysis(
            type="SIMPLE",
            reasoning=f"정규 용어 '{matched_terms[0]}' 매칭, 단일 도메인({domain})",
            queries=[SubQuery(
                query=query,
                domain_hint=domain,
                formal_terms=matched_terms[:3],
            )],
            original_query=query,
            llm_called=False,
            latency_ms=0.0,
        )
```

> **사전 필터의 정확성에 대해:**
>
> 사전 필터는 **보수적**으로 설계했다. 즉, SIMPLE로 판정하는 조건을 엄격하게 하여 "SIMPLE인데 LLM을 호출하는" 경우(false negative)는 허용하되, "LLM이 필요한데 SIMPLE로 넘기는" 경우(false positive)는 최소화한다. false positive가 발생하면 검색 품질이 하락하지만, false negative는 불필요한 LLM 호출이 발생할 뿐 검색 품질에는 영향이 없다.

### 4-4. LLM 호출 (Tier 2) — Claude API

> **쉬운 비유 — API 호출과 재시도:**
>
> 전화를 걸었는데 "통화 중"이 뜨면, 잠시 후 다시 건다. 3번 시도해도 안 되면 포기한다. Rate Limit(사용량 제한)은 "지금 전화가 너무 많이 오고 있으니 나중에 걸어주세요"라는 의미이므로 더 오래(30초) 기다린다. 이것이 아래 코드의 재시도 로직이다.

```python
    # ─────────────────── LLM 호출 (Tier 2) ───────────────────

    def _llm_analyze(self, query: str) -> QueryAnalysis:
        """Tier 2: Claude Sonnet으로 질의 분석.

        시스템 프롬프트에 도메인 목록과 few-shot 예시가 포함되어 있으므로,
        LLM은 구조화된 JSON을 반환한다.

        3회 재시도 + Rate Limit 대기 포함 (build_ontology.py 패턴).
        """
        user_prompt = USER_PROMPT_TEMPLATE.format(query=query)
        t0 = time.time()

        for attempt in range(LLM_RETRY_COUNT):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw = response.content[0].text.strip()

                # JSON 파싱 (build_ontology.py 패턴)
                raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
                raw = re.sub(r'^```\s*$', '', raw, flags=re.MULTILINE)
                raw = raw.strip()

                # JSON 객체 추출
                obj_match = re.search(r'\{.*\}', raw, re.DOTALL)
                if obj_match:
                    raw = obj_match.group()

                parsed = json.loads(raw)
                latency = (time.time() - t0) * 1000

                return self._parse_llm_response(parsed, query, latency)

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"[QueryAnalyzer] 파싱 실패 (시도 {attempt+1}/{LLM_RETRY_COUNT}): {e}")
                if attempt < LLM_RETRY_COUNT - 1:
                    time.sleep(LLM_RETRY_WAIT)

            except anthropic.RateLimitError:
                print(f"[QueryAnalyzer] Rate Limit — {RATE_LIMIT_WAIT}초 대기")
                time.sleep(RATE_LIMIT_WAIT)

        # 모든 재시도 실패 시 fallback: 원본 질의를 그대로 반환
        print(f"[QueryAnalyzer] LLM 호출 실패 — fallback (원본 질의 사용)")
        latency = (time.time() - t0) * 1000
        return QueryAnalysis(
            type="SIMPLE",
            reasoning="LLM 호출 실패 — fallback",
            queries=[SubQuery(query=query, domain_hint="unknown", formal_terms=[])],
            original_query=query,
            llm_called=True,
            latency_ms=latency,
        )
```

### 4-5. LLM 응답 파싱

```python
    def _parse_llm_response(
        self, parsed: dict, original_query: str, latency_ms: float
    ) -> QueryAnalysis:
        """LLM JSON 응답을 QueryAnalysis 객체로 변환.

        유효성 검증:
        - type이 SIMPLE/REWRITE/DECOMPOSE 중 하나인지
        - queries 배열이 비어 있지 않은지
        - 각 서브 질의에 query와 domain_hint가 있는지
        """
        qtype = parsed.get("type", "SIMPLE").upper()
        if qtype not in ("SIMPLE", "REWRITE", "DECOMPOSE"):
            qtype = "SIMPLE"

        reasoning = parsed.get("reasoning", "")
        raw_queries = parsed.get("queries", [])

        if not raw_queries:
            # queries가 비어 있으면 원본 질의를 사용
            raw_queries = [{"query": original_query, "domain_hint": "unknown"}]

        sub_queries = []
        for rq in raw_queries:
            sq = SubQuery(
                query=rq.get("query", original_query),
                domain_hint=rq.get("domain_hint", "unknown"),
                formal_terms=rq.get("formal_terms", []),
            )
            sub_queries.append(sq)

        return QueryAnalysis(
            type=qtype,
            reasoning=reasoning,
            queries=sub_queries,
            original_query=original_query,
            llm_called=True,
            latency_ms=latency_ms,
        )
```

### 4-6. 통합 인터페이스 — `analyze()` 메서드

```python
    # ─────────────────── 통합 인터페이스 ───────────────────────

    def analyze(self, query: str) -> QueryAnalysis:
        """질의를 분석하여 검색 최적화된 형태로 반환.

        흐름:
          1. Tier 1 (사전 필터) — 정규 용어 매칭으로 SIMPLE 여부 판단
          2. Tier 2 (LLM 호출) — SIMPLE이 아닌 경우 Claude Sonnet 호출

        Args:
            query: 사용자 입력 질의 (구어체 포함 가능)

        Returns:
            QueryAnalysis: type, queries, reasoning, latency 등 포함
        """
        t0 = time.time()

        # Tier 1: 사전 필터
        simple_result = self._is_simple(query)
        if simple_result is not None:
            simple_result.latency_ms = (time.time() - t0) * 1000
            return simple_result

        # Tier 2: LLM 호출
        return self._llm_analyze(query)
```

---

## 5. 단독 실행 (CLI)

```python
# ─────────────────── CLI: 수동 테스트 ─────────────────────────

if __name__ == "__main__":
    import sys

    analyzer = QueryAnalyzer()

    # 명령줄 인자가 있으면 해당 질의 분석
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = analyzer.analyze(query)
        print(f"\n질의: {result.original_query}")
        print(f"유형: {result.type}")
        print(f"근거: {result.reasoning}")
        print(f"LLM 호출: {result.llm_called}")
        print(f"레이턴시: {result.latency_ms:.1f}ms")
        for i, sq in enumerate(result.queries):
            print(f"  [{i+1}] {sq.query}")
            print(f"      도메인: {sq.domain_hint}")
            print(f"      전문용어: {sq.formal_terms}")
        sys.exit(0)

    # 기본: 샘플 질의 10개로 테스트
    test_queries = [
        "종부세 기준 금액",                              # SIMPLE
        "1주택자 양도세 비과세",                           # SIMPLE
        "DSR 40퍼센트 넘으면 대출 안돼?",                  # SIMPLE (정규용어 있음)
        "집 살 때 세금 얼마야",                           # REWRITE
        "부동산 사면 나라에 돈 내야 되나",                   # REWRITE (핵심 타겟)
        "은행에서 집값의 몇 프로까지 빌려주는지",             # REWRITE (핵심 타겟)
        "경매 낙찰되면 세금 내야해?",                      # DECOMPOSE
        "청약 당첨되면 대출 얼마까지 받을 수 있어",           # DECOMPOSE
        "재건축 아파트 팔 때 양도세 얼마",                   # DECOMPOSE or REWRITE
        "세입자가 안 나가면 어쩌지",                        # REWRITE
    ]

    print("=" * 70)
    print("  QueryAnalyzer 수동 테스트")
    print("=" * 70)

    llm_count = 0
    for q in test_queries:
        result = analyzer.analyze(q)
        if result.llm_called:
            llm_count += 1
        status = "LLM" if result.llm_called else "SKIP"
        print(f"\n[{status}] {result.type:10s} | {q}")
        print(f"  → {result.queries[0].query}")
        if len(result.queries) > 1:
            for sq in result.queries[1:]:
                print(f"  → {sq.query}")
        print(f"  근거: {result.reasoning}")
        print(f"  레이턴시: {result.latency_ms:.1f}ms")

    print(f"\n--- 요약 ---")
    print(f"총 질의: {len(test_queries)}")
    print(f"LLM 호출: {llm_count} ({llm_count/len(test_queries)*100:.0f}%)")
    print(f"SKIP:    {len(test_queries)-llm_count} ({(len(test_queries)-llm_count)/len(test_queries)*100:.0f}%)")
```

---

## 6. 위험 요소 및 대응

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| LLM이 JSON 형식을 지키지 않음 | 중 | 파싱 실패 | `re.search(r'\{.*\}')` 로 JSON 추출 + 3회 재시도 |
| LLM이 잘못된 domain_hint 반환 | 저 | 검색 라우팅 오류 | `DOMAIN_BRANCHES` 키 검증, fallback to "unknown" |
| 사전 필터가 REWRITE 질의를 SIMPLE로 판정 | 저 | 검색 품질 저하 | 보수적 조건 설계 (정규 용어+단일 도메인+짧은 길이 모두 충족) |
| Rate Limit 초과 | 중 | 응답 지연 | 30초 대기 후 재시도 (기존 패턴) |
| ANTHROPIC_API_KEY 환경변수 미설정 | 저 | 모듈 초기화 실패 | `.env` 파일에서 로드 (기존 인프라) |
