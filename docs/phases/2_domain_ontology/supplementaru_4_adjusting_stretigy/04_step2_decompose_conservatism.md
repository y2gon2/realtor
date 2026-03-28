# Step 2 — DECOMPOSE 보수적 적용 (3단계 방어)

> 작성일: 2026-03-28
> 선행 문서: `01_sequential_improvement_plan.md` §3, `03_step1_hybrid_strategy.md`
> 목적: DECOMPOSE 회귀 5건을 0건으로 감소, 단일 주제 질의의 불필요한 분해 방지
> 수정 파일: `codes/query/prompts.py`, `codes/query/analyzer.py`
> 상태: **구현 완료**, 벤치마크 실행 대기

---

## 0. 문제 정의

### 0-1. DECOMPOSE 회귀 5건 패턴

42개 벤치마크에서 DECOMPOSE는 **개선 0건, 회귀 5건**이다.

```
[회귀 사례 — Cross-Domain Set C]
원본: "재건축 투표 결과가 양도세에 영향 주나요?"

DECOMPOSE 결과:
  ① "재건축 조합 투표 절차"        → 재건축 도메인 결과
  ② "양도소득세 과세 기준"          → 세금 도메인 결과

문제: "투표 결과 → 양도세 영향"이라는 핵심 인과관계가 분리됨
     원본 통합 검색 시 정답이 Top-3에 있었으나,
     분해 후 관련 없는 개별 결과로 대체됨
```

> **쉬운 비유 — 주문 분리:**
>
> 식당에서 "스테이크에 어울리는 와인 추천해줘"라고 주문했을 때:
> - **REWRITE** (좋음): "스테이크와 어울리는 레드 와인" — 하나의 질의로 처리
> - **DECOMPOSE** (나쁨): ① "스테이크 추천" ② "와인 추천" — 분리하면 **페어링이라는 핵심 맥락이 사라진다**
>
> "A하면 B는 어떻게 되나?"라는 질문에서 A와 B를 분리하면 안 되는 이유가 이것이다.

### 0-2. 핵심 원인

| 원인 | 설명 |
|------|------|
| 인과관계 무시 | "A하면 B는?"에서 A→B 관계를 끊고 각각 검색 |
| 단일 도메인 과분해 | 같은 세금 도메인의 세부 질문을 2개로 분리 |
| 맥락 소실 | 원본의 통합된 의미가 서브 질의에서 보존되지 않음 |

---

## 1. Query Decomposition이란?

> **쉬운 비유 — 병원 진료:**
>
> 환자가 "배도 아프고 머리도 아파요"라고 말하면, 의사는 "복부 증상"과 "두통 증상"으로 나누어 각각 전문 진료를 한다.
> - 복부는 내과로, 두통은 신경과로 보내서 각 분야의 전문 의사가 진단한다.
>
> 이것이 Query Decomposition이다. **복합 질의를 분해하여 각각 검색**하면 더 정확한 결과를 얻을 수 있다.
>
> **그러나** "머리 아프고 열 나요"를 "두통"과 "발열"로 분리 진료하다가, 핵심 원인(독감)을 놓치는 것도 가능하다. 이것이 DECOMPOSE 회귀의 원인이다.

### 1-hop vs Multi-hop

> **쉬운 비유 — 도서관 조사:**
>
> **1-hop (단순 조사)**: "한국 GDP가 얼마야?" → 책 한 권만 찾으면 됨
> **2-hop (복합 조사)**: "한국과 일본의 GDP를 비교해줘" → 두 나라 각각 조사 후 비교
> **3-hop (심층 조사)**: "한국의 GDP 성장이 부동산 시장에 미친 영향을 일본 사례와 비교" → 여러 단계 조사 필요
>
> 1-hop 질의를 불필요하게 분해하면 오히려 결과가 나빠진다.

---

## 2. 이론적 배경 — 외부 연구

### 2-1. DecomposeRAG — hop 수별 분해 효과 (핵심 정량 근거)

| hop 수 | 분해 효과 | 의미 |
|--------|---------|------|
| 1-hop | **+1.3%** | 거의 무의미 — 분해 오버헤드만 추가 |
| 3-hop | **+82.2%** | 극적 개선 — 분해가 효과적 |
| 4+hop | **+156.3%** | 분해 필수 |

**결론**: 단순 질의(1-hop)에서 분해는 해롭다. 2+ hop에서만 유효하다.

### 2-2. Decomposed Prompting (Khot et al., ICLR 2023)

- **논문**: "Decomposed Prompting: A Modular Approach for Solving Complex Tasks"
- **핵심**: single-hop에서 분해는 latency만 추가하고 error를 도입한다
- **정량**: multi-hop +10~20% 정확도, single-hop에서는 0% 또는 마이너스
- 출처: https://arxiv.org/abs/2210.02406

### 2-3. Self-Ask (Press et al., ICLR 2023)

- **논문**: "Measuring and Narrowing the Compositionality Gap in Language Models"
- **핵심**: LLM이 먼저 "follow-up question이 필요한가?"를 판단 → 불필요한 분해 방지
- **정량**: 2WikiMultiHopQA +8%, 단순 질의에서는 회귀 없음
- **적용**: 우리의 "인과 패턴 감지 → DECOMPOSE 차단"이 동일 논리
- 출처: https://arxiv.org/abs/2210.03350

### 2-4. IRCoT (Trivedi et al., ACL 2023)

- **논문**: "Interleaving Retrieval with Chain-of-Thought Reasoning"
- **핵심**: 한 번에 전부 분해하지 않고, retrieve → reason → refine → retrieve 반복이 더 효과적
- **적용**: 현 단계에서는 과도한 복잡도이나, DECOMPOSE 대신 REWRITE 우선 사용의 이론적 근거
- 출처: https://arxiv.org/abs/2212.10509

---

## 3. 3단계 방어 전략

> **쉬운 비유 — 자동차 3중 안전장치:**
>
> 1. **안전벨트** (방어 1: 프롬프트 보수화): 애초에 LLM이 DECOMPOSE를 남발하지 않도록 지침 강화
> 2. **에어백** (방어 2: 자동 변환): 프롬프트가 실패해도 코드 레벨에서 잘못된 DECOMPOSE를 REWRITE로 전환
> 3. **차체 구조** (방어 3: 하이브리드 전략): 모든 방어가 실패해도 원본 검색이 결과에 포함되어 보호

### 3-1. 방어 1 — 프롬프트 보수화 (prompts.py)

**DECOMPOSE 허용 조건** (모두 충족 시만):

| # | 조건 | 예시 |
|---|------|------|
| ✓ | 2개 이상의 **완전히 독립적**인 주제 | "전세대출 받고 청약도 가능?" |
| ✓ | 각 서브 질의가 원본 맥락 없이도 의미 완전 | 대출과 청약은 독립적 |
| ✓ | 서브 질의 간 인과/조건/비교 관계 없음 | "A하면 B는?" 형태 아님 |

**DECOMPOSE 금지 조건** (하나라도 해당 시 → REWRITE):

| # | 패턴 | 예시 |
|---|------|------|
| ✗ | "A하면 B가 어떻게 되나" (인과) | "재건축하면 양도세 어떻게 돼?" |
| ✗ | "A와 B 중 어느 것이" (비교) | "전세와 월세 뭐가 나아?" |
| ✗ | "A일 때 B는" (조건) | "다주택자일 때 양도세는?" |
| ✗ | 단일 도메인 내 세부 질문 | "취득세 감면 요건과 세율" |

**프롬프트 내 예시 변경**:

| 원래 질의 | 기존 유형 | 변경 후 유형 | 근거 |
|----------|---------|-----------|------|
| "경매 낙찰되면 세금 내야해?" | DECOMPOSE | **REWRITE** | "낙찰 → 세금" 인과관계 |
| "재건축 투표와 양도세 영향" | DECOMPOSE | **REWRITE** | "투표 → 양도세" 인과관계 |
| "집 계약하고 등기 언제 해야 돼" | DECOMPOSE | **DECOMPOSE** (유지) | 계약과 등기는 독립 절차 |

### 3-2. 방어 2 — 단일 도메인 자동 변환 (analyzer.py L345~351)

> **쉬운 비유 — 자동 교정:**
>
> 스마트폰의 자동 고침(auto-correct)처럼, LLM이 잘못 판단해도 코드가 자동으로 교정한다.
> "같은 병원(도메인) 내에서 과(科)를 나눌 필요 없다"는 규칙이다.

```python
# analyzer.py — _parse_llm_response() 내부 (L345~351)

# P1-a-3: 단일 도메인 DECOMPOSE → REWRITE 자동 변환
if qtype == "DECOMPOSE" and len(sub_queries) > 1:
    domains = set(sq.domain_hint for sq in sub_queries)
    if len(domains) == 1:
        qtype = "REWRITE"
        sub_queries = [sub_queries[0]]
        reasoning += " [DECOMPOSE→REWRITE: 단일 도메인]"
```

**이 코드가 처리하는 사례**:

| LLM 판정 | 서브 질의 | 도메인 | 자동 변환 |
|----------|---------|--------|---------|
| DECOMPOSE | ① 취득세 세율 ② 취득세 감면 | tax, tax | → REWRITE (단일 도메인) |
| DECOMPOSE | ① 경매 절차 ② 취득세 납부 | auction, tax | 유지 (2개 도메인) |

### 3-3. 방어 3 — Step 1 하이브리드가 최종 안전망

방어 1, 2를 모두 통과한 DECOMPOSE라도 Step 1의 하이브리드 전략이 작동한다:
- 원본 질의가 weight 1.2로 검색에 참여
- 서브 질의가 모두 실패해도 원본 결과가 Top-K에 포함

---

## 4. 벤치마크 실행

```bash
python3 codes/query/test_query_decomposition.py \
    --set all \
    --output results/p1a_step2_decompose.json
```

---

## 5. 성공 기준

| 기준 | 임계값 | 근거 |
|------|--------|------|
| DECOMPOSE 회귀 | 0건 | 42개 기준 -5건 → 0건 |
| DECOMPOSE 발생 빈도 | ≤ 10% (50/500) | 현재 ~28% → 보수화로 감소 |
| Set C P@3 | ≥ 81.0% | Cross-domain 보호 |
| 전체 P@3 | ≥ Step 1 결과 | 누적 개선 |

---

## 6. 폴백 계획

DECOMPOSE를 완전히 비활성화:

```python
# config.py에 추가
ENABLE_DECOMPOSE = False  # 모든 DECOMPOSE → REWRITE 강제 전환
```

---

## 7. 절대 하지 말 것

- **인과관계 질의를 DECOMPOSE로 처리** — "A하면 B는?" 형태는 반드시 REWRITE
- **서브 질의에서 원본 키워드 생략** — 각 서브 질의에 원본의 핵심 용어 최소 1개 포함
- **서브 질의 4개 이상 허용** — 과도한 분해는 맥락 소실을 가속화
- **방어 2(자동 변환) 로직 비활성화** — 이것이 없으면 LLM의 잘못된 DECOMPOSE를 잡을 수 없음

---

## 8. 실행 체크리스트

- [ ] `prompts.py` DECOMPOSE 허용/금지 조건 확인
- [ ] `prompts.py` 예시가 보수적으로 변경되었는지 확인
- [ ] `analyzer.py` 단일 도메인 DECOMPOSE→REWRITE 자동 변환 확인
- [ ] 단위 테스트: 인과 패턴 질의("경매 낙찰되면 세금?")가 REWRITE로 처리되는지 확인
- [ ] 500개 벤치마크 실행
- [ ] DECOMPOSE 발생 빈도 ≤ 10% 확인

---

## 9. 참고 문헌

| 자료 | 출처 |
|------|------|
| Decomposed Prompting (Khot et al., ICLR 2023) | https://arxiv.org/abs/2210.02406 |
| Self-Ask (Press et al., ICLR 2023) | https://arxiv.org/abs/2210.03350 |
| IRCoT (Trivedi et al., ACL 2023) | https://arxiv.org/abs/2212.10509 |
| Adaptive-RAG (Jeong et al., NAACL 2024) | https://arxiv.org/abs/2403.14403 |
| DecomposeRAG | 논문 |
