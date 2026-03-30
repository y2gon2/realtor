# Step 4 — 프롬프트 보수성 강화 (키워드 보존)

> 작성일: 2026-03-28
> 선행 문서: `05_step3_prefilter_refinement.md`, `02_execution_overview.md`
> 목적: REWRITE 회귀 2건을 0건으로 감소, 원본 키워드 소실 방지
> 수정 파일: `codes/query/prompts.py`, `codes/query/analyzer.py`
> 상태: **구현 완료**, 벤치마크 실행 대기

---

## 0. 문제 정의

### 0-1. 키워드 소실 사례

42개 벤치마크에서 REWRITE 시 원본 키워드가 소실되는 문제가 2건 확인되었다.

```
[키워드 소실 사례]
원본: "아파트 양도세 비과세 요건"
REWRITE: "1세대 1주택 비과세 조건"
소실된 키워드: "아파트", "양도세"

결과: "양도세"라는 키워드로 잘 매칭되던 온톨로지 엔트리가
      검색 결과에서 빠짐 → P@3 하락
```

> **쉬운 비유 — 법률 문서 번역:**
>
> 법률 문서를 번역할 때, "취득세(acquisition tax)"를 "거래세(transaction tax)"로 의역하면 법적 의미가 달라진다.
> **핵심 법률 용어는 원어 그대로 보존**해야 하듯, 검색 질의의 핵심 키워드도 변환 과정에서 반드시 보존해야 한다.

---

## 1. 이론적 배경 — 외부 연구

### 1-1. Query2Doc — 원본 보존 원칙 (Wang et al., EMNLP 2023)

- **핵심**: pseudo-document를 원본에 **prepend**하지, 원본을 **대체**하지 않음
- **BM25에서의 구체적 기법**: 원본 질의를 **5× 반복** 후 pseudo-document와 결합
  ```
  q_new = q × 5 ++ d   (BM25용)
  q_new = q ++ [SEP] ++ d   (Dense용)
  ```
- **적용**: REWRITE도 원본 키워드를 보존하면서 추가 용어를 확장하는 방식이어야 함
- 출처: https://aclanthology.org/2023.emnlp-main.585/

### 1-2. DMQR-RAG — 4가지 Rewriting 전략 (Li et al., 2024)

- **논문**: "DMQR-RAG: Diverse Multi-Query Rewriting for RAG"
- **4가지 전략**:
  1. **GQR** (General Query Refinement): 노이즈 제거, 핵심 정보 유지
  2. **KWR** (Keyword Rewriting): 검색엔진 선호 키워드 추출
  3. **PAR** (Pseudo Answer Rewriting): 가설 답변 생성 (HyDE와 유사)
  4. **CCE** (Core Concept Extraction): 핵심 개념 집중 추출
- **적용**: KWR이 우리 시스템에 가장 적합 — 부동산 전문용어를 키워드로 추출 후 보존
- 출처: https://arxiv.org/abs/2411.13154

### 1-3. 한국어 교착어 특성

> **쉬운 비유 — 영어 단어 vs 한국어 조사 결합:**
>
> 영어: "house" → 항상 "house"
> 한국어: "집" → "집을", "집이", "집에", "집의", "집에서" 등으로 변형
>
> 한국어는 **교착어(agglutinative language)**로, 어근에 조사/어미가 붙어 다양한 형태로 변한다.
> "양도소득세를 납부"에서 "양도소득세"를 추출하려면 형태소 분석(morphological analysis)이 필요하다.
> BGE-M3 Sparse 벡터가 이를 부분적으로 처리하지만, 프롬프트 레벨에서도 키워드 보호가 필요하다.

**한국어 BM25 토크나이저 비교** (AutoRAG 벤치마크):

| 토크나이저 | Top-1 F1 | Top-3 Recall |
|-----------|---------|-------------|
| **Okt** | **0.7982** | **0.9561** |
| Kkma | 0.7544 | 0.9298 |
| Kiwi | 0.7281 | 0.8860 |
| 공백 분리 | 0.6667 | — |

출처: https://github.com/Marker-Inc-Korea/AutoRAG-example-tokenizer-benchmark

---

## 2. 변경 상세

### 2-1. 프롬프트 보수적 원칙 (prompts.py L56~66)

현재 프롬프트의 **핵심 원칙** 섹션:

```python
## 핵심 원칙: 보수적 판단

1. **SIMPLE 우선**: 전문용어가 1개 이상 포함된 질의는 SIMPLE로 판정하세요.
   벡터 검색은 전문용어가 있으면 잘 작동합니다.

2. **REWRITE는 최소 변환**: 변환 시 원본 질의의 핵심 키워드를 반드시 포함하세요.
   원본 키워드를 제거하고 완전히 다른 표현으로 바꾸지 마세요.

3. **DECOMPOSE는 극히 제한적**: 서브 질의가 완전히 독립적이고
   별개의 검색이 필요한 경우에만 사용합니다.
   "A 하면 B는?" 형태는 DECOMPOSE가 아닌 REWRITE로 처리합니다.
```

REWRITE 규칙 (prompts.py L64~65):

```python
- REWRITE: queries에 정제된 질의 1개만 포함,
  구어체→전문용어 변환 필수. 원본 핵심 키워드 보존 필수.
```

### 2-2. 사전 분석 컨텍스트 전달 (prompts.py L107~116 + analyzer.py L264~274)

> **쉬운 비유 — 통역사에게 사전 브리핑:**
>
> 국제 회의 전에 통역사에게 "오늘 회의에서 LTV, DSR, 종부세가 핵심 용어입니다"라고 알려주면,
> 통역사가 이 용어들을 정확히 처리할 수 있다.
>
> 마찬가지로, LLM에게 사전 필터가 감지한 정보를 전달하면 더 정확한 판단을 내릴 수 있다.

**User Prompt 템플릿** (prompts.py L107~116):

```python
USER_PROMPT_TEMPLATE = """다음 부동산 질의를 분석하세요:

"{query}"

사전 분석 결과:
- 감지된 전문용어: {matched_terms}
- 감지된 도메인: {detected_domains}
- 인과 패턴 포함: {has_causal}

JSON으로만 응답하세요."""
```

**컨텍스트 생성** (analyzer.py L264~274):

```python
def _llm_analyze(self, query: str) -> QueryAnalysis:
    # P1-a-4: 사전 분석 컨텍스트 전달
    matched_terms = self._find_matching_terms(query)
    detected_domains = self._detect_domains(query)
    has_causal = self._has_causal_pattern(query)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        query=query,
        matched_terms=matched_terms[:5] if matched_terms else "없음",
        detected_domains=detected_domains if detected_domains else "미감지",
        has_causal="예" if has_causal else "아니오",
    )
```

### 2-3. REWRITE 후처리 검증 (analyzer.py L251~260)

```python
def _validate_rewrite(self, original: str, rewritten: str) -> str:
    """P1-a-4: 변환 질의에서 원본 핵심 용어 소실 시 보충.

    원본에 포함된 정규 용어가 변환 결과에 없으면,
    변환 결과 뒤에 누락된 용어를 보충한다.

    예시:
      원본: "아파트 양도세 비과세 요건"
      변환: "1세대 1주택 비과세 조건"
      소실: "양도세"
      보정: "1세대 1주택 비과세 조건 양도세"
    """
    original_terms = self._find_matching_terms(original)
    if not original_terms:
        return rewritten
    missing = [t for t in original_terms if t not in rewritten]
    if missing:
        supplement = " ".join(missing[:3])
        return f"{rewritten} {supplement}"
    return rewritten
```

이 함수는 `_parse_llm_response()` 내부에서 REWRITE 결과에 자동 적용된다 (L340~343):

```python
# P1-a-4: REWRITE 질의의 원본 키워드 보존 검증
if qtype == "REWRITE":
    for sq in sub_queries:
        sq.query = self._validate_rewrite(original_query, sq.query)
```

---

## 3. 변환 사례 비교

| 원본 | 변경 전 REWRITE | 변경 후 REWRITE | 차이 |
|------|---------------|---------------|------|
| "아파트 양도세 비과세 요건" | "1세대 1주택 비과세 조건" | "1세대 1주택 비과세 조건 **양도세**" | 양도세 보충 |
| "재건축 아파트 팔 때 양도세 얼마" | "재건축 아파트 양도소득세 세율" | 동일 (키워드 보존됨) | 변화 없음 |
| "전세 보증금 못 받으면 어떡해" | "임차보증금 미반환 시 대항력 행사" | "임차보증금 미반환 시 대항력 행사 **전세 보증금**" | 전세, 보증금 보충 |

---

## 4. 벤치마크 실행

```bash
python3 codes/query/test_query_decomposition.py \
    --set all \
    --output results/p1a_step4_prompt.json
```

---

## 5. 성공 기준

| 기준 | 임계값 | 근거 |
|------|--------|------|
| REWRITE 회귀 | 0건 | 42개 기준 -2건 → 0건 |
| Set B P@3 | ≥ 60% | 구어체 변환 효과 |
| Set E P@3 | ≥ 58% | 슬랭 변환 효과 |
| 전체 P@3 | ≥ Step 3 결과 | 누적 개선 |

---

## 6. 절대 하지 말 것

- **원본에 없는 새 개념을 변환 결과에 추가** — 검색 범위가 의도치 않게 확대됨
- **변환 결과가 원본의 2배 이상 길어지게 하기** — 임베딩 공간에서 의미가 희석됨
- **정규 용어 질의를 불필요하게 REWRITE** — 전문용어가 이미 있으면 SIMPLE이 맞음
- **_validate_rewrite() 로직 비활성화** — 이것이 없으면 키워드 소실을 잡을 수 없음

---

## 7. 실행 체크리스트

- [ ] `prompts.py` 보수적 원칙 3가지 확인
- [ ] `prompts.py` USER_PROMPT_TEMPLATE에 사전 분석 컨텍스트 포함 확인
- [ ] `analyzer.py` _validate_rewrite() 후처리 확인
- [ ] `analyzer.py` _parse_llm_response()에서 REWRITE 시 _validate_rewrite() 호출 확인
- [ ] 단위 테스트: 키워드 소실 사례에서 보충되는지 확인
- [ ] 500개 벤치마크 실행
- [ ] REWRITE 회귀 0건 확인

---

## 8. 참고 문헌

| 자료 | 출처 |
|------|------|
| Query2Doc (Wang et al., EMNLP 2023) | https://aclanthology.org/2023.emnlp-main.585/ |
| DMQR-RAG (Li et al., 2024) | https://arxiv.org/abs/2411.13154 |
| RaFe (Mao et al., EMNLP 2024 Findings) | https://aclanthology.org/2024.findings-emnlp.49/ |
| Korean Tokenizer Benchmark (AutoRAG) | https://github.com/Marker-Inc-Korea/AutoRAG-example-tokenizer-benchmark |
| Query Rewriting in RAG (Shekhar Gulati, 2024) | https://shekhargulati.com/2024/07/17/query-rewriting-in-rag-applications/ |
