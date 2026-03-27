# 확장 벤치마크 — 설정 A~F 비교 계획

> 작성일: 2026-03-27
> 선행 문서: `05_benchmark_and_ablation.md`, `07_colbert_improvement_research.md`, `08_reranker_module_design.md`
> 목적: 기존 설정 A~D에 신규 설정 E(Cross-Encoder), F(3-Way RRF)를 추가하여 6개 설정 간 정량 비교를 수행하고, 최적 운영 설정을 결정

---

## 1. 확장 설정 정의

### 1-1. 전체 설정 매트릭스

| 설정 | 모델 | 벡터 구성 | 퓨전 | 리랭킹 | 구현 위치 | 상태 |
|------|------|----------|------|--------|----------|------|
| A | KURE-v1 | Dense + Kiwi BM25 | RRF | — | Qdrant | 완료 |
| B | BGE-M3 | Dense only | — | — | Qdrant | 완료 |
| **C** | **BGE-M3** | **Dense + Sparse** | **RRF** | **—** | **Qdrant** | **완료 (현재 운영)** |
| D | BGE-M3 | Dense + Sparse + ColBERT | ColBERT MaxSim | — | Qdrant | 완료 (성능 저하) |
| **E** | **BGE-M3** | **Dense + Sparse** | **RRF** | **Cross-Encoder** | **Qdrant + Client** | **신규** |
| **F** | **BGE-M3** | **Dense + Sparse + ColBERT** | **RRF (3-way)** | **—** | **Qdrant** | **신규** |

### 1-2. 신규 설정 상세

#### 설정 E: D+S RRF + Cross-Encoder Reranking

```
[Qdrant] Dense(100) + Sparse(100) → RRF → top-50
                                       ↓
[Client] bge-reranker-v2-m3-ko → sigmoid score [0,1] → top-10
```

> **쉬운 비유:** 온라인 쇼핑몰에서 AI가 추천 상품 50개를 뽑은 뒤(RRF), 전문 큐레이터(Cross-Encoder)가 50개를 직접 살펴보고 최종 10개를 선정하는 방식.

#### 설정 F: D+S+ColBERT 3-Way RRF

```
[Qdrant] Dense(50) + Sparse(50) + ColBERT(50) → RRF(3-way) → top-10
```

> **쉬운 비유:** 3명의 심사위원(Dense, Sparse, ColBERT)이 각자 50명의 후보를 추천하고, 투표(RRF)로 최종 10명을 선정. ColBERT가 "독재"하지 못하고 1표만 행사한다.

---

## 2. 실행 순서

### Phase 1: 설정 F (3-Way RRF) — 퀵 벤치마크 (0.5일)

**이유**: 코드 변경이 가장 적다 (prefetch 1줄 추가 + query 변경만).

| 단계 | 작업 | 소요 시간 |
|------|------|----------|
| 1 | `search_test_phase2_v2.py`에 `three_way_rrf` 모드 추가 | 30분 |
| 2 | 45개 질의 벤치마크 실행 | 10분 |
| 3 | 결과 분석 및 기록 | 30분 |

**성공 기준:**

| 지표 | 기준 | 의미 |
|------|------|------|
| P@3 | ≥ 90% | Setting C(92%)와 동등 수준 |
| 기존 성공 질의 유지 | 0건 이하 하락 | 회귀 없음 |

**의사결정:**
- P@3 ≥ 92%이면 → 3-Way RRF를 운영 설정으로 전환 검토
- P@3 < 90%이면 → D+S RRF(Setting C) 유지, Phase 2 진행

### Phase 2: 설정 E (Cross-Encoder) — 모듈 구축 (2~3일)

| 단계 | 작업 | 소요 시간 |
|------|------|----------|
| 1 | `codes/embedding/reranker.py` 생성 (08 문서 기반) | 2시간 |
| 2 | `index_phase2_v2.py` payload에 `embedding_text` 추가 | 30분 |
| 3 | v2 컬렉션 재인덱싱 (`--force`) | 30분 |
| 4 | `search_test_phase2_v2.py`에 `hybrid_rrf_rerank` 모드 추가 | 1시간 |
| 5 | `benchmark_phase2_v2.py`에 설정 E, F 추가 | 1시간 |
| 6 | 45개 질의 벤치마크 실행 (설정 C/E/F 비교) | 20분 |
| 7 | 결과 분석, 실패 질의 심층 분석 | 2시간 |

**성공 기준:**

| 지표 | 기준 | 의미 |
|------|------|------|
| P@3 | ≥ 94% | Setting C(92%) 대비 +2%p 이상 |
| Avg Top-1 Ontology | ≥ 0.82 | Setting C(0.791) 대비 +3.7% |
| 기존 성공 질의 유지 | 0건 이하 하락 | 회귀 없음 |
| Latency p95 | < 500ms | 서비스 수준 유지 |

**의사결정:**
- 모든 기준 달성 → Cross-Encoder를 프로덕션 reranker로 채택
- P@3 ≥ 94%이지만 레이턴시 초과 → reranker 후보 수 축소 (50→30) 후 재시도
- P@3 < 94% → Phase 3(compute_score 가중 퓨전) 진행

---

## 3. 환경 설정

### 3-1. 모델 설치

```bash
# FlagEmbedding은 이미 설치됨 (embedder_bgem3.py 사용 중)
# bge-reranker-v2-m3-ko는 첫 실행 시 HuggingFace에서 자동 다운로드 (~1.1GB)

# 다운로드 확인 (선택사항):
python3 -c "from FlagEmbedding import FlagReranker; FlagReranker('dragonkue/bge-reranker-v2-m3-ko')"
```

### 3-2. GPU 메모리 예산

> **쉬운 비유 — GPU 메모리 = 책상 위 공간:**
>
> 공부할 때 책상에 교과서, 노트, 참고서를 올려놓아야 한다. 책상이 작으면 한 번에 하나만 펼칠 수 있고(swap), 크면 다 올려놓고 빠르게 왔다갔다 할 수 있다. GPU 메모리도 마찬가지로, 모델 여러 개를 동시에 올려야 빠르다.

| 구성 요소 | FP16 메모리 | 역할 |
|-----------|-----------|------|
| Qdrant 서버 | ~2GB | 벡터 DB (별도 프로세스) |
| BGE-M3 (BGEM3FlagModel) | ~3GB | 임베딩 (3종 벡터 추출) |
| bge-reranker-v2-m3-ko | ~2GB | 리랭킹 |
| Python + PyTorch 오버헤드 | ~1GB | 런타임 |
| **합계** | **~8GB** | — |
| **DGX Spark 가용** | **128GB** | 여유: **120GB** |

→ 메모리 제약 없음. 모든 모델 동시 로드 가능.

### 3-3. Qdrant 컬렉션 확인

```bash
# v2 컬렉션 상태 확인
curl -s http://localhost:6333/collections/domain_ontology_v2 | python3 -m json.tool | grep points_count
# 예상: "points_count": 2146

curl -s http://localhost:6333/collections/legal_docs_v2 | python3 -m json.tool | grep points_count
# 예상: "points_count": 775
```

---

## 4. 검증 계획

### 4-1. 45개 질의 A/B 비교

기존 `05_benchmark_and_ablation.md`의 45개 질의(온톨로지 25개 + 법률 20개)를 설정 C/E/F에 대해 실행하고, **질의별** 결과를 비교한다.

```
비교 매트릭스 (질의 × 설정):

              Setting C    Setting E    Setting F
질의 1         ✓ (Top-1)   ✓ (Top-1)   ✓ (Top-1)
질의 2         ✓           ✗ → 원인?    ✓
...
질의 45        ✓           ✓           ✗ → 원인?
```

### 4-2. 실패 질의 2개 집중 분석

설정 C에서도 실패하는 2개 질의에 대해 설정 E(Cross-Encoder)가 해결하는지 집중 확인:

| 질의 | Setting C 결과 | 기대 키워드 | Setting E 기대 |
|------|---------------|-----------|-------------|
| "부동산 사면 나라에 돈 내야 되나" | X (공과금) | 취득세 | Cross-Encoder가 "나라에 돈"↔"취득세" 맥락 연결 가능? |
| "은행에서 집값의 몇 프로까지 빌려주는지" | X (시장이자율) | LTV, 담보비율 | Cross-Encoder가 "빌려주는"↔"LTV" 연결 가능? |

> **참고**: 이 2개 질의는 Query Rewriting(P1-a)으로 해결될 가능성이 더 높다. Cross-Encoder가 해결하지 못해도 설정 E의 전체적 가치는 유효하다.

### 4-3. 레이턴시 프로파일링

각 설정에 대해 45개 질의의 레이턴시를 측정하고, 분포를 분석한다.

```
측정 지표:
  - p50 (중간값): 일반적인 응답 시간
  - p95 (95번째 백분위수): "거의 항상 이 이하" 응답 시간
  - p99 (99번째 백분위수): 최악에 가까운 응답 시간
  - max: 가장 느린 응답 시간
```

> **쉬운 비유 — 식당 대기 시간:**
>
> p50은 "보통 이 정도 기다린다", p95는 "바쁜 날에도 이 정도면 끝난다", p99는 "아주 운 나쁜 날"이다. 서비스 품질 보장은 보통 p95 기준으로 한다.

| 설정 | 예상 p50 | 예상 p95 | 예상 p99 |
|------|---------|---------|---------|
| C (D+S RRF) | ~8ms | ~48ms | ~55ms |
| E (+ Cross-Encoder) | ~150ms | ~285ms | ~400ms |
| F (3-Way RRF) | ~10ms | ~55ms | ~65ms |

### 4-4. 회귀 테스트

> **쉬운 설명 — 회귀 테스트(Regression Test)란?**
>
> 새로운 기능을 추가한 뒤, **기존에 잘 동작하던 것이 깨지지 않았는지** 확인하는 테스트. 스마트폰 업데이트 후 "전화 잘 되나?", "카메라 잘 찍히나?" 확인하는 것과 같다.

확인 항목:

| 항목 | 확인 방법 | 합격 기준 |
|------|----------|----------|
| 기존 성공 질의 보존 | Setting C에서 Top-3에 포함된 정답이 Setting E/F에서도 Top-3에 포함 | 0건 이하 회귀 |
| Top-1 스코어 하락 | 각 질의의 Top-1 정답 스코어가 기존 대비 0.05 이상 하락하는 경우 | 0건 이하 |
| 레이턴시 한도 | p95 레이턴시 | < 500ms |

---

## 5. 위험 요소 및 대응

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| Cross-Encoder 모델 다운로드 실패 | 낮 | Phase 2 지연 | 사전 다운로드 (`huggingface-cli download`), 로컬 캐시 확인 |
| Reranker가 RRF보다 나쁜 결과 | 중 | 설정 E 폐기 | 설정 C 유지. reranker 후보 수 조정 (50→30→20) 후 재시도 |
| 3-Way RRF에서 ColBERT가 노이즈 | 중 | 설정 F 성능 미달 | DBSF 퓨전으로 교체 시도 (분포 기반 정규화) |
| `embedding_text` payload 누락 | 낮 | Reranker 입력 없음 | 재인덱싱 전 payload 스키마 확인. fallback으로 term+aliases 사용 |
| GPU 메모리 부족 (BGE-M3 + Reranker 동시) | 매우 낮 | 모델 로드 실패 | DGX Spark 128GB에서 ~8GB만 필요. 문제 없음 |
| 벤치마크 결과 재현 불가 | 낮 | 비교 신뢰도 저하 | 동일 환경/쿼리/시드 사용, JSON 결과 저장 |

---

## 6. 결과 기록 계획

벤치마크 완료 후 다음 문서를 작성한다:

| 문서 | 내용 | 작성 시점 |
|------|------|----------|
| `10_expanded_benchmark_results.md` | 설정 A~F 전체 비교 결과, 질의별 상세 분석, 최종 운영 설정 결정 | Phase 1+2 완료 후 |

### 결과 테이블 예시 (기대)

| 설정 | Onto P@3 | Onto Avg Top-1 | Legal Avg Top-1 | Latency p95 | 판정 |
|------|----------|---------------|-----------------|-------------|------|
| A: v1 KURE-v1 | 84% | 0.619 | 0.612 | — | 기준선 |
| B: v2 Dense only | 80% | 0.633 | 0.656 | 45ms | — |
| **C: v2 D+S RRF** | **92%** | **0.791** | **0.734** | **48ms** | **현재 운영** |
| D: v2 D+S+ColBERT | 72% | 6.66* | 7.19* | 60ms | 폐기 |
| **E: v2 D+S RRF + CE** | **94%?** | **0.82?** | **0.78?** | **285ms?** | **후보** |
| **F: v2 3-Way RRF** | **90%?** | **0.03?** | **0.03?** | **55ms?** | **후보** |

> ? 표시는 예상치이며 실측 후 확정.

---

## 7. 성과 궤적 (Phase 2 누적, 기대)

```
Phase 2 검색 성능 개선 궤적:

Precision@3:
  Baseline (Phase 2 초기):       80%
  + Contextual Retrieval (P0-a):  90%   (+10%p)
  + BGE-M3 D+S RRF (P0-b):      92%   (+2%p)   ← 현재
  + Cross-Encoder (P0-b-2):      94%?  (+2%p?)  ← 목표

Avg Top-1 Ontology:
  Baseline:                      0.611
  + Contextual Retrieval:        0.630  (+3.1%)
  + BGE-M3 D+S RRF:             0.791  (+25.6%)  ← 현재
  + Cross-Encoder:               0.82?  (+3.7%?) ← 목표
```
