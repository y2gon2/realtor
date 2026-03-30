# Phase 2A 벤치마크 및 검증 계획

> 작성일: 2026-03-28
> 선행 문서: `02_alpha_grid_search.md`, `03_conditional_ce_bypass.md`, `04_slang_alias_expansion.md`
> 관련 코드: `codes/query/test_query_decomposition.py`
> 목적: Phase 2A 3개 작업의 통합 검증 방법, 실행 절차, 결과 분석 기준 정의

---

## 1. 검증 전략 개요

### 1-1. 3단계 벤치마크

```
Step 1: α 그리드 서치 (작업 1-A)
    → 최적 전역 α 확인
    → 세트별 α 경향 파악

Step 2: 중간 벤치마크 (작업 1-B + 2-A + 2-B)
    → 조건부 α + CE 우회 + CE 정규화의 통합 효과 확인
    → Set A 회귀 없음 확인

Step 3: 최종 벤치마크 (작업 3 적용 후)
    → 슬랭 alias 확장의 추가 효과 확인
    → 전체 목표 ≥72% 달성 여부
```

### 1-2. 비교 기준선 (Baseline)

| 설정 | P@3 | 출처 |
|------|-----|------|
| **Baseline** (벡터 검색만) | 65.8% | `10_expanded_benchmark_results.md` |
| **Full** (Step 1-4, CE 없음) | 67.2% | `08_step1to4_results.md` |
| **Full+Rerank** (Step 5, α=0.5) | 68.0% | `09_step5_rerank_results.md` |
| **Phase 2A** (목표) | **≥72%** | 본 문서 |

---

## 2. Step 1: α 그리드 서치

### 2-1. 실행

```bash
# Docker 컨테이너 내부
docker exec -it rag-embedding bash

# α 그리드 서치 (500개 질의 × 9개 α = 4,500회 CE predict)
python3 codes/query/test_query_decomposition.py \
    --alpha-grid \
    --output results/alpha_grid.json
```

> **소요 시간**: 약 2시간 (CE predict ~1.5초/질의 × 500 × 9 = 6,750초 ≈ 112분)
> CE 모델 최초 로딩 ~37초는 1회만 발생.

### 2-2. 결과 분석 방법

```bash
# 결과 JSON 확인
python3 -c "
import json
data = json.load(open('results/alpha_grid.json'))
for alpha, sets in sorted(data.items()):
    print(f'α={alpha}: 전체={sets[\"overall\"][\"p3\"]}%')
"
```

**확인 사항**:
1. Set A는 α 증가에 따라 P@3가 상승하는가? (CE 신뢰도↑)
2. Set B는 α 감소에 따라 P@3가 상승하는가? (CE 비중↓)
3. 전체 최적 α는 0.5 대비 개선되는가?

---

## 3. Step 2: 중간 벤치마크 (작업 1+2 통합)

### 3-1. 실행

```bash
# 조건부 α + CE 우회 + CE 정규화가 자동 적용됨
python3 codes/query/test_query_decomposition.py \
    --setting full_rerank \
    --output results/phase2a_step12.json
```

> **중요**: `pipeline.py`에 구현된 `_resolve_alpha()`, `_should_skip_rerank()`, min-max 정규화가 자동 적용된다. `rerank_alpha=0.5`(기본값)이 전달되면 내부에서 조건부 α로 오버라이드.

### 3-2. 4-Way 비교표 생성

기대 결과 형식:

```
  세트      Baseline   Full    Full+Rerank  Phase2A(1+2)  변화
  ───────────────────────────────────────────────────────────
  A (150)   79.3%     78.0%    79.0%         80.0%         +1%p
  B (50)    46.0%     58.0%    56.0%         60.0%         +4%p
  C (100)   81.0%     81.0%    81.0%         81.0%          0%p
  D (100)   50.0%     55.0%    57.0%         58.0%         +1%p
  E (100)   56.0%     54.0%    55.0%         55.0%          0%p
  전체      65.8%     67.2%    68.0%         70.0%         +2%p
```

### 3-3. 성공 기준

| 지표 | 기준 | 통과 조건 |
|------|------|---------|
| Set A P@3 | ≥ 79% | 회귀 없음 |
| Set B P@3 | ≥ 58% | Full 수준 복원 |
| 전체 P@3 | ≥ 70% | +2%p 이상 |
| CE 스킵율 | ~25% | 구어체에 집중 |

### 3-4. 실패 시 대응

| 문제 | 원인 추정 | 대응 |
|------|---------|------|
| Set A 회귀 | α=0.7이 과도 | SIMPLE_FORMAL α를 0.6으로 하향 |
| Set B 미개선 | 스킵 임계값이 너무 높음 | COLLOQUIAL_SKIP_THRESHOLD를 2로 하향 |
| 전체 P@3 < 69% | α 조건 분기가 효과 없음 | 전역 최적 α로 고정 |

---

## 4. Step 3: 최종 벤치마크 (작업 3 적용 후)

### 4-1. 사전 조건

```bash
# 1. 슬랭 매핑 생성
python3 codes/ontology/expand_slang_aliases.py

# 2. 매핑 검수 (수동)
cat ontology_data/slang_alias_mapping.json | python3 -m json.tool

# 3. 엔트리 적용 (dry-run 먼저)
python3 codes/ontology/apply_slang_aliases.py --dry-run

# 4. 실제 적용
python3 codes/ontology/apply_slang_aliases.py

# 5. 재색인
python3 codes/embedding/index_phase2_v2.py --only ontology --force
```

### 4-2. 최종 벤치마크 실행

```bash
# 5-Way 비교: Baseline / Full / Full+Rerank / Phase2A(1+2) / Phase2A(전체)
python3 codes/query/test_query_decomposition.py \
    --setting full_rerank \
    --output results/phase2a_final.json
```

### 4-3. 최종 성공 기준

| 세트 | 현재 | 목표 | 핵심 레버 |
|------|------|------|---------|
| A (정규) | 79% | **≥ 79%** | 조건부 α (CE 강화) |
| B (극단 구어체) | 56% | **≥ 60%** | CE 우회 + 슬랭 alias |
| C (크로스도메인) | 81% | **≥ 81%** | 회귀 없음 |
| D (구어체) | 57% | **≥ 59%** | 조건부 α |
| E (혼합/슬랭) | 55% | **≥ 60%** | 슬랭 alias 확장 |
| **전체** | **68.0%** | **≥ 72%** | 합산 +4%p |

---

## 5. 결과 문서화

### 5-1. 결과 파일 저장 위치

```
results/
├── alpha_grid.json               ← Step 1 결과
├── phase2a_step12.json           ← Step 2 결과 (중간)
└── phase2a_final.json            ← Step 3 결과 (최종)
```

### 5-2. 결과 분석 문서

최종 벤치마크 완료 후, 아래 문서를 작성:

```
supplementary_5_slang_alias_ce/
└── 06_phase2a_results.md         ← 최종 결과 리포트
```

내용:
1. 3단계 벤치마크 결과표 (5-Way 비교)
2. 세트별 회귀/개선 분석
3. CE 스킵 비율 통계
4. α 그리드 서치 최적값 분석
5. 슬랭 alias 효과 분석
6. Phase 2B 권고 사항

---

## 6. 성과 궤적 (Phase 2 누적)

```
Phase 2 검색 성능 궤적:

── 25개 질의 ──
  Phase 2 초기:                   80%
  + Contextual Retrieval:         90%   (+10%p)
  + BGE-M3 D+S RRF:              92%   (+2%p)

── 500개 질의 확장 ──
  Baseline (Setting C):           65.8%
  + Full Pipeline (Step 1-4):     67.2%  (+1.4%p)
  + Full+Rerank (Step 5):        68.0%  (+2.2%p)

── Phase 2A Quick Wins ──
  + α 최적화 + CE 우회:          ~70%   (+2%p, 예상)
  + 슬랭 alias 확장:             ~72%   (+2%p, 예상)
  ─────────────────────────────
  Phase 2A 최종:                 ≥72%   (목표)
```
