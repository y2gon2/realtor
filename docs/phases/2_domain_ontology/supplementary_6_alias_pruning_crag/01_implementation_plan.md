# Phase 2A 미구현 사항 구현 계획 — Alias Pruning + CRAG 보정 검색

> 작성일: 2026-03-29
> 선행 문서: `supplementary_5_slang_alias_ce/06_phase2a_results.md` §6, §8, §9
> 목적: Phase 2A 벤치마크에서 권장되었으나 미구현된 4개 항목 구현

---

## 0. 배경 및 동기

### Phase 2A 최종 성과 (06_phase2a_results.md §8-3)

| 세트 | Step 5 (이전 최고) | Phase 2A 최종 | 변화 | 판정 |
|------|-----------------|-------------|------|------|
| A (정규 150) | 79% | 77% | -2%p | **미달** |
| B (구어체 50) | 56% | **60%** | +4%p | 달성 |
| C (교차 100) | 81% | **82%** | +1%p | 달성 |
| D (구어체 100) | 57% | **58%** | +1%p | 개선 |
| E (슬랭 100) | 55% | 54% | -1%p | **미달** |
| **전체** | **68.0%** | **68.0%** | 0%p | 동등 |

### 미구현 사항 4가지

| # | 항목 | 현황 | 영향 |
|---|------|------|------|
| 1 | Alias max 18 제한 | 20으로 설정됨, 소급 미적용 | Set A 벡터 희석 |
| 2 | Alias pruning 소급 적용 | 미구현 | 최대 25개 엔트리 방치 |
| 3 | Set A 벡터 희석 해결 | 미해결 | 79% → 77% 회귀 |
| 4 | Self-RAG / CRAG 답변 보상 | 미구현 | Set E 54%, 목표 60% 미달 |

→ 항목 1-3은 **작업 1 (Alias Pruning)**으로 통합, 항목 4는 **작업 2 (CRAG Compensator)**로 분리.

### 목표

| 지표 | 현재 | 목표 |
|------|------|------|
| Set A P@3 | 77% | **≥79%** (회복) |
| Set E P@3 | 54% | **≥60%** |
| 전체 P@3 | 68% | **≥70%** |

---

## 1. 작업 1 — Alias Pruning & Max-18 Enforcement

> 상세 문서: `02_alias_pruning_script.md`

### 1-1. 문제 진단

Phase 2A에서 슬랭 alias 359개를 추가한 결과:
- Set B/D/C는 개선 (+4%p/+1%p/+1%p)
- **Set A는 -2%p 회귀** (79% → 77%)

회귀 원인 분석 (06_phase2a_results.md §3-3, §9-5):

| 원인 | 기여도 | 근거 |
|------|--------|------|
| alias 과다로 임베딩 벡터 희석 | -1.3%p | Baseline 79.3% → 78% (alias 추가만으로 하락) |
| REWRITE 회귀 (12건) | -0.7%p | 정규 질의가 불필요하게 REWRITE됨 |

**벡터 희석(Vector Dilution)이란?**

> 비유: 도서관에서 책을 찾을 때, 카탈로그 카드에 "부동산 세금"이라고만 적혀 있으면 정확히 찾을 수 있다. 그런데 같은 카드에 "집 사면 돈 내는 거", "아파트 세금 뜻", "세금이 뭐야" 같은 문구를 20개씩 적어놓으면? 카드의 핵심 정보가 희석되어 오히려 찾기 어려워진다.
>
> 임베딩도 마찬가지다. BGE-M3 모델이 "취득세 | 집 살 때 세금 | 다주택자 취득세 중과..."라는 텍스트를 1024차원 벡터 하나로 압축할 때, alias가 너무 많으면 핵심 의미가 벡터 공간에서 분산되어 정확한 매칭이 어려워진다. 이를 **벡터 희석**이라 한다.

### 1-2. 해결 전략

1. `MAX_ALIASES_PER_ENTRY` 20 → 18 변경
2. 소급 pruning 스크립트로 초과 엔트리 정리
3. Validator에 max alias 경고 추가
4. 재색인 후 벤치마크 검증

### 1-3. 수정 대상 파일

| 파일 | 변경 | 유형 |
|------|------|------|
| `codes/ontology/apply_slang_aliases.py` | line 28: 20 → 18 | 수정 (1줄) |
| `codes/ontology/prune_aliases.py` | 소급 pruning 스크립트 | **신규** |
| `codes/ontology/validator.py` | max alias 경고 추가 | 수정 (3줄) |

### 1-4. 기대 효과

| 세트 | 현재 | 예상 | 근거 |
|------|------|------|------|
| A | 77% | **79-80%** | alias 희석 -1.3%p 해소 + 잔여 REWRITE 개선 |
| B~D | 60/82/58% | 유지 | 보호 alias로 슬랭 매핑 보존 |
| E | 54% | 54-55% | alias pruning 단독으로는 미미 |

---

## 2. 작업 2 — CRAG Retrieval Compensator

> 상세 문서: `03_crag_retrieval_compensator.md`

### 2-1. 문제 진단

Set E 실패 패턴 (06_phase2a_results.md §3-4, §9-6):

| 실패 유형 | 비율 | 예시 |
|-----------|------|------|
| 슬랭 어휘 격차 | ~35% | "영끌" → "과다차입" 매핑 실패 |
| 복합 슬랭+다중도메인 | ~30% | "영끌해서 집 샀는데 이자 감당 안 되면 경매?" |
| DECOMPOSE 회귀 | ~15% | 복합 슬랭의 부정확한 분해 |
| CE 정규화 노이즈 | ~20% | 슬랭 질의에서 CE 점수 극단적 |

**핵심 인사이트** (§9-6): "Set E는 검색 최적화의 한계. 복합 슬랭+다중도메인 질의는 **LLM 답변 보상 전략**(Self-RAG, CRAG)이 필요."

### 2-2. 해결 전략: CRAG 기반 보정 검색

검색 결과의 품질을 평가하고, 낮은 경우 LLM이 정규 용어를 제안하여 재검색:

```
기존: Query → Embed → Search → [CE Rerank] → Return

추가: ... → [CE Rerank] → Evaluator(query, top3)
       → CORRECT:   그대로 반환 (추가 비용 0)
       → AMBIGUOUS:  보정 쿼리로 부분 재검색 → Merge
       → INCORRECT:  보정 쿼리로 전면 재검색
```

### 2-3. 참고 연구

| 논문 | 발표 | 핵심 기법 | 본 프로젝트 적용 |
|------|------|-----------|-----------------|
| **CRAG** (Yan et al.) | ICLR 2025 | 검색 신뢰도 3단계 평가 → 보정 | 검색 후 평가 → 재검색 루프 |
| **Self-RAG** (Asai et al.) | NeurIPS 2023 | Reflection tokens로 적응적 검색 | Rule-based fast path |
| **FILCO** | 2024 | 저관련성 패시지 필터링 (EM +8.6%) | AMBIGUOUS 문서 필터링 |
| **TA-ARE** | 2025 | 학습 임계값으로 불필요 검색 감소 14.9% | 점수 기반 CORRECT 자동 판정 |

### 2-4. 수정 대상 파일

| 파일 | 변경 | 유형 |
|------|------|------|
| `codes/query/compensator_prompts.py` | 평가 프롬프트 | **신규** |
| `codes/query/compensator.py` | Evaluator + Compensator 클래스 | **신규** |
| `codes/query/config.py` | CRAG 상수 7개 추가 | 수정 |
| `codes/query/pipeline.py` | CRAG 통합 (~15줄) | 수정 |
| `codes/query/test_query_decomposition.py` | `full_rerank_crag` 설정 | 수정 |

### 2-5. 기대 효과

| 세트 | 현재 | 예상 | 근거 |
|------|------|------|------|
| A | 79%* | 79% | CORRECT fast path → 변동 없음 |
| B | 60% | 60-62% | 일부 구어체에서 추가 개선 가능 |
| C | 82% | 82% | 이미 높음, fast path |
| D | 58% | 58-60% | 구어체 보정 효과 |
| E | 54%* | **60-65%** | 슬랭→정규 용어 보정 재검색 핵심 |

*Alias Pruning 적용 후 기준

---

## 3. 실행 순서

```
Phase A: Alias Pruning (작업 1)
  ① apply_slang_aliases.py MAX 20→18 변경
  ② prune_aliases.py 신규 작성
  ③ validator.py max alias 경고 추가
  ④ Dry-run → Apply → Validate
  ⑤ 재색인 + Set A 벤치마크 (목표 ≥79%)

Phase B: CRAG Compensator (작업 2)      ← 코드 작성은 Phase A와 병렬 가능
  ⑥ compensator_prompts.py 작성
  ⑦ compensator.py 작성
  ⑧ config.py CRAG 상수 추가
  ⑨ pipeline.py CRAG 통합
  ⑩ test_query_decomposition.py 설정 추가

Phase C: 통합 검증
  ⑪ Set E 벤치마크 (목표 ≥60%)
  ⑫ 전체 회귀 체크 (A≥79%, B≥58%, C≥82%, D≥56%)
```

---

## 4. 재사용 기존 함수 (수정 없이 호출)

| 함수 | 파일 | 용도 |
|------|------|------|
| `embed_query()` | `codes/embedding/embedder_bgem3.py` | 보정 쿼리 임베딩 |
| `search_ontology()` | `codes/embedding/search_test_phase2_v2.py` | 보정 검색 |
| `rrf_merge()` | `codes/query/merger.py` | 초기+보정 결과 병합 |
| `_call_claude_cli()` 패턴 | `codes/query/analyzer.py:236-256` | CRAG 평가 LLM 호출 |
| `_find_matching_terms()` | `codes/query/analyzer.py:141-147` | formal_terms 검증 |

---

## 5. 리스크 및 완화

| 리스크 | 확률 | 완화 |
|--------|------|------|
| Alias pruning 후 Set B/D 회귀 | 중 | 보호 alias (manual_verified) 보존 |
| CRAG LLM 호출 비용 증가 | 중 | Rule-based fast path로 ~55% 스킵 |
| CRAG 평가 LLM 할루시네이션 | 저 | formal_terms를 온톨로지 용어 세트로 검증 |
| 재색인 실패 | 저 | 백업 + prune_log.json 롤백 |
