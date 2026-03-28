# Step 3 — 사전 필터 정교화 (LLM 호출율 88% → ≤60%)

> 작성일: 2026-03-28
> 선행 문서: `04_step2_decompose_conservatism.md`, `02_execution_overview.md`
> 목적: LLM 호출율을 88%에서 ≤60%로 감소시켜 비용과 레이턴시를 절감하되, 구어체 오판 0건 유지
> 수정 파일: `codes/query/config.py`, `codes/query/analyzer.py`
> 상태: **구현 완료**, 벤치마크 실행 대기

---

## 0. 문제 정의

### 0-1. 현재 비효율

42개 벤치마크에서 LLM 호출율이 **88%** (37/42)이다. 전문용어가 명확한 질의에도 불필요하게 LLM을 호출한다.

```
[불필요한 LLM 호출 예시]
질의: "양도소득세 세율이 궁금합니다"
→ 사전 필터: SIMPLE 조건 불충족 (길이 > 15자)
→ LLM 호출 → type=SIMPLE, 원본 그대로 반환
→ 결과: LLM 비용만 소모, 검색 결과 동일
```

> **쉬운 비유 — 공항 보안 검색:**
>
> 현재: "가방 크기 15cm 이하"만 통과 → 대부분 정밀 검색(LLM) 대상
> 개선: 기준 완화(25cm) + VIP 패스(전문용어 2개+) → LLM 호출 절반 감소
>
> VIP 패스 = 전문용어가 2개 이상 있으면 "이 사람은 정확히 뭘 찾는지 안다"고 판단하는 것이다.

---

## 1. 이론적 배경 — 외부 연구

### 1-1. PruneRAG (Jiao et al., 2026)

- **논문**: "PruneRAG: Confidence-Guided Query Decomposition Trees for Efficient RAG"
- **핵심**: LLM 토큰별 신뢰도가 0.95 이상이면 검색 자체를 건너뜀
- **정량**: 평균 검색 호출 **6.73 → 2.06회** (4.9× 효율 향상)
- 출처: https://arxiv.org/abs/2601.11024

> **쉬운 비유 — 학교 시험:**
>
> "2+3=?"은 바로 답을 쓸 수 있고, "미적분 응용 문제"는 풀이 과정이 필요하다.
> PruneRAG는 **쉬운 문제에 긴 풀이를 쓰지 않도록** 문제 난이도를 먼저 판단하는 것이다.
> 우리 시스템도 마찬가지로, 전문용어가 이미 포함된 질의는 LLM의 도움이 필요 없다.

### 1-2. Adaptive-RAG (Jeong et al., NAACL 2024)

- **논문**: "Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity"
- **핵심**: T5-Large 분류기로 질의 복잡도 3단계 분류
  - A단계: 검색 불필요 (LLM 자체 지식)
  - B단계: 단일 검색 (한 번이면 충분)
  - C단계: 다단계 검색 (여러 번 필요)
- **정량**: 평균 검색 단계 4.69 → 2.17 (53% 감소), 평균 시간 8.81s → 3.60s
- 출처: https://arxiv.org/abs/2403.14403

### 1-3. RAGRouter-Bench (Wang et al., 2026)

- **논문**: "RAGRouter-Bench: A Dataset and Benchmark for Adaptive RAG Routing"
- **핵심 발견**: "No single RAG paradigm is universally optimal" — 질의별 최적 전략이 다름
- **적용**: 우리의 SIMPLE/REWRITE/DECOMPOSE 3단 라우팅이 동일 논리
- 출처: https://arxiv.org/abs/2602.00296

---

## 2. 변경 상세

### 2-1. MAX_SIMPLE_LENGTH 확장 (config.py L22)

```python
MAX_SIMPLE_LENGTH = 25   # P1-a-2: 15 → 25 (한국어 질의 특성)
```

**변경 근거**: 한국어 부동산 질의의 평균 길이는 20~25자이다. "양도소득세 세율이 궁금합니다" (14자)가 SIMPLE로 판정되어야 하지만, 기존 15자 기준으로는 통과하지 못하는 사례가 다수 존재했다.

### 2-2. 정규 용어 사전 확장 (analyzer.py L71~134)

```python
def _load_formal_terms(self) -> None:
    """entries/*.json + taxonomy.json + 약어 사전을 로드하여 캐싱.

    3가지 소스에서 로드:
    1) entries/*.json — 기존: ~21,000 entries의 term + aliases
    2) taxonomy.json — 신규: 59개 도메인 카테고리명
    3) COMMON_ABBREVIATIONS — 신규: 약어 사전 (종부세, 양도세 등)

    결과: ~25,000+ terms의 set
    set lookup: O(1), 메모리: ~2MB
    """
```

> **O(1)이란?**
>
> 데이터가 아무리 많아도 검색 시간이 일정하다는 뜻이다.
> Python의 `set`은 해시 테이블 기반이므로, 25,000개의 용어 중에서
> "취득세"가 포함되어 있는지 확인하는 데 걸리는 시간은 항상 동일하다.

### 2-3. 도메인 키워드 맵 (config.py L44~65)

```python
DOMAIN_KEYWORDS_SEED = {
    "tax":            ["세금", "취득세", "양도세", "종부세", "재산세", "상속", "증여",
                       "과세", "양도소득세", "상속세", "증여세", "등록면허세", "인지세", "보유세"],
    "loan":           ["대출", "LTV", "DSR", "DTI", "담보", "금리", "이자", "빌려",
                       "주택담보대출", "전세대출", "보금자리론", "디딤돌대출"],
    "subscription":   ["청약", "분양", "통장", "가점", "특별공급", "당첨",
                       "분양가상한제", "분양권"],
    "rental":         ["전세", "월세", "보증금", "임대", "임차", "세입자", "집주인",
                       "계약갱신", "전월세", "임대사업자"],
    "auction":        ["경매", "공매", "낙찰", "입찰", "배당", "명도",
                       "법원경매", "유찰", "임장"],
    "contract":       ["계약", "중개", "거래", "매매", "매매계약",
                       "중개수수료", "중개보수", "전세사기", "복비"],
    "reconstruction": ["재건축", "재개발", "안전진단", "조합", "리모델링",
                       "관리처분", "조합원입주권"],
    "regulation":     ["규제", "조정대상", "투기", "공시가격", "다주택",
                       "투기과열", "공시지가", "토지거래허가"],
    "land":           ["토지", "지목", "용적률", "건폐율", "농지",
                       "용도지역", "개발행위", "감정평가", "지적"],
    "registration":   ["등기", "근저당", "전세권", "소유권", "가압류",
                       "가처분", "지상권", "등기부등본"],
}
```

### 2-4. 다중 요소 SIMPLE 판정 (analyzer.py L173~225)

> **쉬운 비유 — 건강검진 사전 문진표:**
>
> 병원에 가면 먼저 간단한 문진표를 작성한다. 4가지 항목을 체크하여 "정밀 검사가 필요한가"를 판단:
> 1. 기존 병력이 있나? (정규 용어가 있나?)
> 2. 증상이 경미한가? (질의가 짧은가?)
> 3. 한 곳만 아픈가? (단일 도메인인가?)
> 4. 말이 분명한가? (구어체가 아닌가?)
>
> 4가지 모두 "예"이면 간단 처방(SIMPLE), 하나라도 "아니오"이면 전문의(LLM) 진료.

```python
def _is_simple(self, query: str) -> QueryAnalysis | None:
    """Tier 1: 룰 기반 사전 필터 (P1-a-2 다중 요소 판정).

    SIMPLE이면 QueryAnalysis 반환, 아니면 None (Tier 2 LLM으로 전달).
    6개의 Gate를 순차적으로 통과해야 SIMPLE로 판정된다.
    """
    matched_terms = self._find_matching_terms(query)
    detected_domains = self._detect_domains(query)
    domains_from_terms = self._detect_domains_from_terms(matched_terms)
    has_causal = self._has_causal_pattern(query)

    # Gate 1: 정규 용어 0개 → 반드시 LLM
    if not matched_terms:
        return None

    # Gate 2: 25자 초과 → 복합 질의 가능성
    if len(query) > MAX_SIMPLE_LENGTH:
        return None

    # 도메인 합산 (키워드 + 용어 매핑)
    all_domains = set(detected_domains) | set(domains_from_terms)

    # Gate 3: 3+ 도메인 → 복합 질의
    if len(all_domains) >= 3:
        return None

    # Gate 4: 2+ 도메인 + 인과 패턴 → DECOMPOSE 후보
    if len(all_domains) >= 2 and has_causal:
        return None

    # Gate 5: 2+ 도메인 + 정규 용어 1개 이하 → 도메인 불확실
    if len(all_domains) >= 2 and len(matched_terms) < 2:
        return None

    # Gate 6: 구어체 강도 높음 + 용어 적음 → LLM이 도움
    if self._colloquial_score(query) >= 2 and len(matched_terms) <= 1:
        return None

    # 모든 Gate 통과 → SIMPLE
    domain = (detected_domains[0] if detected_domains
              else domains_from_terms[0] if domains_from_terms
              else "unknown")
    return QueryAnalysis(
        type="SIMPLE",
        reasoning=f"정규 용어 매칭({len(matched_terms)}개), 도메인({domain})",
        queries=[SubQuery(query=query, domain_hint=domain, formal_terms=matched_terms[:3])],
        original_query=query,
        llm_called=False,
        latency_ms=0.0,
    )
```

### 2-5. 구어체 마커 (config.py L37~41)

```python
# P1-a-2: 구어체 마커 (구어체 점수 계산용)
COLLOQUIAL_MARKERS = [
    "뭐야", "어쩌", "어떡", "알려줘", "해줘",
    "프로까지", "빌려", "떼가", "나라에", "먹튀",
    "뺏겨", "쪼개", "날리면",
]
```

구어체 점수 계산 (analyzer.py L163~168):
```python
def _colloquial_score(self, query: str) -> int:
    """구어체 마커 수를 카운팅. 높을수록 구어체."""
    score = sum(1 for m in COLLOQUIAL_MARKERS if m in query)
    if not self._find_matching_terms(query):
        score += 2  # 전문용어 없으면 구어체 가능성 높음
    return score
```

---

## 3. 판정 사례 분석

| 질의 | 용어 | 도메인 | 구어체 점수 | 판정 | 이유 |
|------|------|--------|-----------|------|------|
| "양도소득세 세율" | 양도소득세 | tax | 0 | **SIMPLE** | 정규 용어 + 단일 도메인 + 짧음 |
| "집 팔면 세금 얼마야" | 세금 | tax | 3+ | **LLM** | 구어체 점수 ≥ 2 |
| "LTV DTI DSR 차이" | LTV, DTI, DSR | loan | 0 | **SIMPLE** | 정규 약어 3개 + 단일 도메인 |
| "영끌해도 되나" | — | — | 4+ | **LLM** | 전문용어 없음 + 구어체 |

---

## 4. 핵심 원칙: 구어체 오판 방지

**최우선 규칙**: 사전 필터는 **보수적으로 SIMPLE을 판정**해야 한다. 의심스러우면 LLM을 호출하는 것이 안전하다.

구어체 질의를 SIMPLE로 판정하면 검색 품질이 하락하지만, 정규 질의를 SIMPLE로 판정하면 불필요한 LLM 호출만 줄어들 뿐 검색 품질에는 영향이 없다.

→ **False Positive(구어체를 SIMPLE로 오판) = 0건**이 절대 기준.

---

## 5. 벤치마크 실행

```bash
python3 codes/query/test_query_decomposition.py \
    --set all \
    --output results/p1a_step3_prefilter.json
```

---

## 6. 성공 기준

| 기준 | 임계값 | 근거 |
|------|--------|------|
| LLM 호출율 | ≤ 60% | 현재 88% → 28%p 감소 목표 |
| Set A P@3 | ≥ 79.3% | 정규 질의가 SIMPLE로 분류 → 변화 없어야 |
| 구어체 SIMPLE 오판 | **0건** | Set B/D에서 SIMPLE 판정 불가 |
| 전체 P@3 | ≥ Step 2 결과 | 누적 개선 |

---

## 7. 절대 하지 말 것

- **구어체 질의를 SIMPLE로 분류** — 전문용어가 없으면 무조건 LLM 호출
- **MAX_SIMPLE_LENGTH를 30 이상으로 설정** — 복합 질의가 SIMPLE로 오분류될 위험
- **Gate 순서를 변경** — Gate 1(정규 용어 0개 → 반드시 LLM)은 반드시 최우선

---

## 8. 실행 체크리스트

- [ ] `config.py` MAX_SIMPLE_LENGTH=25 확인
- [ ] `config.py` DOMAIN_KEYWORDS_SEED 10개 도메인 확인
- [ ] `config.py` COLLOQUIAL_MARKERS 13개 확인
- [ ] `analyzer.py` _is_simple() 6-Gate 로직 확인
- [ ] 단위 테스트: 정규 질의 → SIMPLE, 구어체 → LLM 확인
- [ ] 500개 벤치마크 실행
- [ ] LLM 호출율 ≤ 60%, 구어체 오판 0건 확인

---

## 9. 참고 문헌

| 자료 | 출처 |
|------|------|
| PruneRAG (Jiao et al., 2026) | https://arxiv.org/abs/2601.11024 |
| Adaptive-RAG (Jeong et al., NAACL 2024) | https://arxiv.org/abs/2403.14403 |
| RAGRouter-Bench (Wang et al., 2026) | https://arxiv.org/abs/2602.00296 |
| Korean Tokenizer Benchmark (AutoRAG) | https://github.com/Marker-Inc-Korea/AutoRAG-example-tokenizer-benchmark |
