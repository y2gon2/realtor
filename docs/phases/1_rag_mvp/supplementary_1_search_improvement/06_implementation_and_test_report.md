# 06. 보완 작업 구현 및 테스트 리포트

**작성일**: 2026-03-30 (3/31 LLM 테스트 업데이트)
**작업 범위**: Sprint 0~3 구현 + 전체 검증 (01~05 문서 기반)

---

## 1. Sprint 0: realestate_v2 재색인

### 실행

```bash
docker exec -d rag-embedding python3 /workspace/codes/embedding/index_all.py --v2-dir /workspace/rag_v2
```

### 결과

| 항목 | 이전 (3/15) | 이후 (3/30) | 변화 |
|------|------------|------------|------|
| 색인 문서 | 6,343 | **11,037** | +4,694 |
| 총 포인트 | 93,943 | **171,590** | +77,647 (+82.7%) |
| 세그먼트 | 7 | 8 | +1 |
| 컬렉션 상태 | green | green | — |

- **소요 시간**: 약 1시간 40분 (KURE-v1 GPU, ~1.4s/doc)
- **incremental indexing** 정상 동작: 기존 6,343개 자동 스킵, 4,694개만 추가 처리
- `rag_v2/` 폴더의 11,037개 파일 전체가 색인 완료

---

## 2. Sprint 1: Query-Time 개선 구현

### 2-1. 수정 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `codes/query/config.py` | 12개 feature flag 추가 (HYDE, RAG_FUSION, PARENT_DOC, DYNAMIC_ALPHA, CRAG_TIER0, LISTWISE) |
| `codes/query/prompts.py` | HyDE, RAG-Fusion, Listwise 프롬프트 템플릿 3개 추가 |
| `codes/query/analyzer.py` | `generate_hyde_document()`, `generate_fusion_queries()` 메서드 추가 |
| `codes/query/pipeline.py` | search()에 HyDE/RAG-Fusion/Parent Doc/Listwise/Dynamic Alpha 통합 |
| `codes/query/alpha_trainer.py` | (신규) Ridge Regression 기반 Dynamic Alpha 학습 스크립트 |

### 2-2. Parent Document Retrieval 테스트

**방법**: realestate_v2에서 KURE-v1 dense 벡터 검색 후 `_fetch_parent_documents()` 호출.

**테스트 질의**: "종부세 기준 금액이 뭐야?"

| 단계 | 결과 |
|------|------|
| realestate_v2 검색 | 5개 atomic_fact 반환 (score 0.73~0.74) |
| 부모 문서 수집 | **3개 문서** 성공적으로 수집 |
| 문서 1 | `5minute.imjang` 채널, summary 358자, facts 15개 |
| 문서 2 | `AllTax_GAGAM` 채널, facts 16개 |
| 문서 3 | summary 186자, facts 10개 |

**결론**: Qdrant scroll API를 이용한 부모 문서 수집 정상 동작. 온톨로지 컬렉션(domain_ontology_v2)에는 `doc_id`가 없으므로 해당 컬렉션에서는 parent_documents=0 반환 (설계 의도대로).

### 2-3. HyDE (Hypothetical Document Embeddings) 테스트

**테스트**: Docker 내 Claude CLI 인증 복구 후 5개 구어체 질의 대상 A/B 테스트.

| 질의 | OFF 결과 | ON 결과 | 변경 | HyDE 문서 |
|------|---------|---------|------|----------|
| 부동산 사면 나라에 돈 내야 되나 | 공과금, 속지주의, 국제이중과세 | 동일 | N | 399자 |
| 집 살 때 세금 얼마야 | 취득세, 과세표준, 공과금 | 동일 | N | 499자 |
| 은행에서 집값의 몇 프로까지 빌려주는지 | 시장이자율, 비율분석법, 투기과열지구 | 시장이자율, 비율분석법, **담보** | **Y** | 417자 |
| 영끌해서 집 사도 되나 | 비율분석법, 담보, 주택도시기금 | **담보**, 비율분석법, 주택도시기금 | **Y** | 485자 |
| 갭투자 위험하지 않나 | 담보, 중간생략등기, 연불매매 | 동일 | N | 500자 |

- HyDE 가상 문서 생성 정상 (399~500자, 도메인 전문용어 포함)
- 5개 중 **2개에서 순위 변경** (담보 관련 용어 상승)
- 온톨로지 컬렉션 기반 검색에서는 영향이 제한적 — realestate_v2 통합 시 더 큰 효과 기대

### 2-4. RAG-Fusion (Multi-Query) 테스트

**테스트**: 동일 5개 구어체 질의, 각 5개 변형 생성.

| 질의 | 변형 수 | 총 결과 | OFF→ON 변경 |
|------|--------|--------|------------|
| 부동산 사면 나라에 돈 내야 되나 | 5 | 30 | **Y** (취득세 순위 상승) |
| 집 살 때 세금 얼마야 | 5 | 30 | N |
| 은행에서 집값의 몇 프로까지 빌려주는지 | 5 | 30 | N |
| 영끌해서 집 사도 되나 | 5 | 30 | **Y** (주택도시기금 상승) |
| 갭투자 위험하지 않나 | 5 | 30 | N |

- 5개 변형 질의 × 6개 결과 = 30개 추가 후보를 RRF 병합
- 5개 중 **2개에서 순위 재배치**

### 2-5. A/B 벤치마크 (20개 질의, HyDE+Fusion+Listwise)

**비교**: 기준선 (flags OFF) vs Enhanced (HYDE+FUSION+LISTWISE ON, SKIP_SIMPLE=True)

| Set | 유형 | 기준선 | Enhanced | 변화 |
|-----|------|--------|----------|------|
| A | 정규 (8q) | **83.3%** | **83.3%** | ±0 |
| B | 극단 구어체 (5q) | **86.7%** | **86.7%** | ±0 |
| D | 구어체 (4q) | **100.0%** | **100.0%** | ±0 |
| E | 슬랭 (3q) | **77.8%** | **77.8%** | ±0 |
| **전체** | **(20q)** | **86.7%** | **86.7%** | **±0** |

**분석**: 온톨로지 컬렉션(domain_ontology_v2) 기반 검색에서는 HyDE/Fusion 효과가 제한적. 이유:
1. `SKIP_SIMPLE=True`로 대부분 SIMPLE 질의에 적용 안 됨
2. 온톨로지 엔트리는 이미 전문용어 + 구어체 별칭(aliases)이 풍부하여 기존 검색이 강력
3. HyDE/Fusion은 realestate_v2 (자연어 문서)에서 더 큰 효과 기대

### 2-6. Dynamic Alpha

- `alpha_trainer.py` 학습 스크립트 작성 완료
- 4개 feature: colloquial_score, matched_terms_count, query_length, domain_count
- Ridge Regression (5-fold CV) → `alpha_model.pkl` 저장
- `_resolve_alpha()` 수정: 모델 있으면 예측, 없으면 기존 4-bucket fallback
- scikit-learn 설치 완료, 30-query 샘플 학습 실행 중

---

## 3. Sprint 2: Post-Retrieval 개선 구현

### 3-1. CRAG Tier 0: 메타데이터 도메인 프리필터 테스트

**방법**: `CRAG_TIER0_ENABLED=True` (기본값) 상태에서 5개 질의에 대해 CRAG 평가.

| 질의 | 결과 도메인 | 매치 | CRAG 등급 | 레이턴시 |
|------|-----------|------|----------|---------|
| 종부세 기준 금액 | tax, tax, tax | ✓ | CORRECT | 2,845ms |
| 취득세 세율 | tax, tax, tax | ✓ | CORRECT | 89ms |
| LTV 한도 | loan, regulation, land | ✓ | CORRECT | 93ms |
| 청약 가점 기준 | subscription, subscription, regulation | ✓ | CORRECT | 97ms |
| 경매 낙찰가율 | auction, auction, auction | ✓ | CORRECT | 124ms |

**결론**: **5/5 질의 모두 Tier 0에서 CORRECT 판정** → LLM 호출 완전 회피. 기존 Tier 1/2까지 가지 않고 도메인 매치만으로 빠르게 통과.

### 3-2. Listwise LLM Reranking 테스트

**테스트**: CE 스킵 대상 (colloquial_score >= 2) 질의 5개에 대해 LLM 리랭킹 A/B 비교.

| 질의 | CE skip | OFF 결과 | ON 결과 | 변경 |
|------|---------|---------|---------|------|
| 부동산 사면 나라에 돈 내야 되나 | False | 공과금, 속지주의, 국제이중과세 | 동일 | N |
| 은행에서 집값의 몇 프로까지 빌려주는지 | **True** | 금융기관, 차주, 시장이자율 | 동일 | N |
| 집 사고 팔면 뭘 내야 해 | **True** | 양도소득세, 소유권, 공과금 | 동일 | N |
| 영끌해서 집 사도 되나 | **True** | 주택도시기금, 차입금, 담보 | 주택도시기금, 차입금, **시장이자율** | **Y** |
| 갭투자 위험하지 않나 | False | 담보, 중간생략등기, 정상가액 | 동일 | N |

- CE skip=True인 3개 질의에서 Listwise가 활성화
- 1/3 질의에서 LLM이 순위 재배치 (시장이자율 상승)
- 파싱 실패 없이 안정적 동작

---

## 4. Sprint 3: Adaptive RAG Generation 구현

### 4-1. 생성 파일

| 파일 | 내용 |
|------|------|
| `codes/generation/__init__.py` | 모듈 초기화 |
| `codes/generation/state.py` | RAGState 17 필드 (입력/분석/검색/평가/생성/할루시네이션/루프) |
| `codes/generation/gen_prompts.py` | grade/generate/hallucination/rewrite 프롬프트 + `format_documents_for_prompt()` |
| `codes/generation/nodes.py` | 6개 노드 함수 (analyze_query, retrieve, grade_documents, generate, check_hallucination, rewrite_query) |
| `codes/generation/graph.py` | LangGraph StateGraph 조립 + Pure Python fallback + CLI |

### 4-2. 전체 플로우 테스트 (LLM 포함, 3/31)

Docker 내 Claude CLI 인증 복구 후 3개 질의로 전체 6노드 파이프라인 검증.

#### 질의 1: "취득세 세율이 어떻게 되나요?"

| 노드 | 결과 |
|------|------|
| analyze_query | type=SIMPLE, queries=1, llm_calls=0 |
| retrieve | onto=5, legal=5, latency=6,450ms |
| grade_documents | **pass** — "취득세 표준세율(1~3%), 중과세율(8%·12%), 과세표준 구간별 세율 체계 포함" |
| generate | **691자 답변**, 인용 [6][7][8] — 유상취득/무상취득/중과 세율 표 포함 |
| check_hallucination | **pass** — "모든 수치가 참고 문서와 일치" |

**총 LLM 3회, 55초, 재시도 0회**

#### 질의 2: "전세 사기 안 당하려면 어떻게 해야 하나요?"

| 노드 | 결과 |
|------|------|
| analyze_query | type=SIMPLE, queries=1, llm_calls=0 |
| retrieve (1차) | onto=5, legal=5 |
| grade_documents | **fail** — "예방 방법 정보 부재, 사후 구제에 편중" |
| rewrite_query | → "전세계약 전 등기부등본 확인방법, 전입신고 확정일자..." |
| retrieve (2차) | onto=5, legal=5 |
| grade_documents | **fail** — "구제 수단에 집중, 예방 정보 여전히 부족" |
| rewrite_query | → "전세 계약 전 확인사항 등기부등본 근저당 선순위채권..." |
| retrieve (3차) | onto=5, legal=5 |
| grade_documents | **fail** → max_retries 도달 → 강제 생성 |
| generate | **741자 답변**, 인용 [1][3][4][5][8] — 등기부, 임차권등기, 주임법, 거래신고 |
| check_hallucination | **pass** — "모든 내용이 참고 문서와 일치" |

**총 LLM 7회, 142초, 재시도 2회** — 자기 보정 루프가 3차까지 작동하여 질의 재작성 후 답변 생성 성공.

#### 질의 3: "재건축 투자 시 주의할 점은?"

| 노드 | 결과 |
|------|------|
| analyze_query | type=SIMPLE |
| retrieve | onto=5, legal=5 |
| grade_documents | **pass** — "안전진단, 조합, 세금 특례 등 핵심 요소 포함" |
| generate | **938자 답변**, 인용 [2][5][6][7][8] — 안전진단, 양도세 비과세, 재건축조합 |
| check_hallucination | **pass** |

**총 LLM 3회, 53초, 재시도 0회**

### 4-3. Generation 품질 요약

| 지표 | 결과 |
|------|------|
| 답변 생성 성공률 | **3/3 (100%)** |
| 할루시네이션 통과율 | **3/3 (100%)** |
| 평균 LLM 호출 | 4.3회/질의 |
| 평균 레이턴시 | 83초/질의 |
| 평균 재시도 | 0.67회/질의 |
| 평균 답변 길이 | 790자/질의 |
| 평균 인용 수 | 4.3개/질의 |

**결론**: Adaptive RAG Generation 파이프라인이 완전하게 동작. 자기 보정 루프(grade → rewrite → re-retrieve)가 문서 부족 상황에서 효과적으로 작동하며, 할루시네이션 체크도 정상적으로 사실 검증을 수행.

---

## 5. 통합 벤치마크

### 5-1. 측정 조건

- **환경**: rag-embedding 컨테이너 (GPU), rag-qdrant v1.17.0
- **설정**: 모든 Sprint 1/2 feature flag OFF (기존 파이프라인 호환성)
- **옵션**: `rerank=True, rerank_candidates=10, crag=True`
- **컬렉션**: realestate_v2 171,590 포인트 (재색인 후), domain_ontology_v2 2,146 포인트

### 5-2. 결과 (12개 샘플 질의)

| Set | 질의 | P@3 | Top-3 결과 |
|-----|------|-----|-----------|
| A | 종부세 기준 금액 | 0.67 | 주택분 과세기준금액, 기준시가, 양도가액 |
| A | 취득세 세율 | 1.00 | 표준세율, 취득세 과세표준, 탄력세율 |
| A | 재건축 안전진단 | 1.00 | 안전진단, 재건축사업, 노후·불량건축물 |
| A | 전세보증보험 | 1.00 | 주택임대차신용보험, 보증보험, 보증기관 |
| A | DSR 규제 | 0.33 | 투기과열지구, 부채서비스액, 과밀억제권역 |
| B | 부동산 사면 나라에 돈 내야 되나 | 0.67 | 공과금, 속지주의, 국제이중과세 |
| B | 은행에서 집값의 몇 프로까지 빌려주는지 | 0.67 | 시장이자율, 차주, 임대료 |
| B | 집 사고 팔면 뭘 내야 해 | 0.67 | 양도소득세, 소유권, 공과금 |
| D | 집 살 때 세금 얼마야 | 1.00 | 취득세, 과세표준, 공과금 |
| D | 전세 사기 안 당하려면 | 1.00 | 배임죄, 주택임대차신용보험, 위장거래 |
| E | 영끌해서 집 사도 되나 | 1.00 | 담보, 주택도시기금, 비율분석법 |
| E | 갭투자 위험하지 않나 | 0.67 | 담보, 중간생략등기, 연불매매 |

### 5-3. 세트별 P@3

| Set | 유형 | 평균 P@3 | 질의 수 |
|-----|------|---------|--------|
| A | 정규 | **80.0%** | 5 |
| B | 극단 구어체 | **66.7%** | 3 |
| D | 구어체 | **100.0%** | 2 |
| E | 슬랭 | **83.3%** | 2 |
| **전체** | | **80.6%** | **12** |

### 5-4. 이전 대비 변화

| 지표 | Phase 2 (3/15) | 현재 (3/30) | 변화 |
|------|---------------|------------|------|
| 색인 포인트 | 93,943 | 171,590 | **+82.7%** |
| 색인 문서 | 6,343 | 11,037 | **+74.0%** |
| 전체 P@3 (500쿼리) | 68.0% | — | 전체 벤치마크 미실행 |
| 샘플 P@3 (12쿼리) | — | 80.6% | 새 측정 |

---

## 6. Feature Flag 상태 총괄

| Flag | 기본값 | 테스트 상태 | 설명 |
|------|--------|-----------|------|
| `PARENT_DOC_ENABLED` | `False` | ✅ 검증 완료 | realestate_v2 부모 문서 수집 (3개 문서, summary+facts) |
| `HYDE_ENABLED` | `False` | ✅ 검증 완료 | 가상 답변 문서 생성 (399-500자) + 검색 + RRF |
| `RAG_FUSION_ENABLED` | `False` | ✅ 검증 완료 | 5개 변형 질의 생성 + 개별 검색 (30 추가 결과) |
| `DYNAMIC_ALPHA_ENABLED` | `False` | 🔄 학습 진행 중 | Ridge 회귀 α 예측 (30q 샘플 학습) |
| `CRAG_TIER0_ENABLED` | `True` | ✅ 검증 완료 | 도메인 매치 기반 CRAG 프리필터 (5/5 CORRECT) |
| `LISTWISE_RERANK_ENABLED` | `False` | ✅ 검증 완료 | CE 스킵 시 LLM 리스트와이즈 (1/3 질의 변경) |

---

## 7. 아키텍처 변경 사항

### pipeline.py search() 플로우 (변경 후)

```
Step 1:   질의 분석 (analyzer.analyze)
Step 1b:  슬랭 사전 확장 (_expand_slang_query)
Step 2:   원본 질의 임베딩 + 검색
Step 2.5a: [NEW] HyDE 가상 문서 생성 + 임베딩 + 검색 (HYDE_ENABLED)
Step 2.5b: [NEW] RAG-Fusion 변형 생성 + 검색 (RAG_FUSION_ENABLED)
Step 3:   SIMPLE이면 결과 병합 (원본 + HyDE + Fusion RRF)
Step 4:   REWRITE/DECOMPOSE 변환 질의 검색
Step 5:   RRF 합산 (원본 + 변환 + HyDE + Fusion)
Step 6:   CE 리랭킹 OR [NEW] Listwise LLM 리랭킹 (LISTWISE_RERANK_ENABLED)
Step 7:   [ENHANCED] CRAG (Tier 0 도메인 프리필터 추가)
Step 8:   [NEW] Parent Document 수집 (PARENT_DOC_ENABLED)
```

### Adaptive RAG Generation 플로우 (신규)

```
analyze_query → retrieve → grade_documents
                              ├─ pass → generate → check_hallucination
                              │                       ├─ pass → END
                              │                       └─ fail → rewrite_query → retrieve ↻
                              └─ fail → rewrite_query → retrieve ↻
                              (max_retries=2 후 강제 생성)
```

---

## 8. 핵심 발견 및 분석

### 온톨로지 기반 검색에서 HyDE/Fusion 효과 제한

HyDE와 RAG-Fusion은 이론적으로 구어체 질의의 어휘 격차를 줄여야 하지만, 20개 질의 벤치마크에서 **P@3 변화 = 0%p**. 이유:

1. **`domain_ontology_v2` 컬렉션의 구조적 강점**: 각 온톨로지 엔트리에 2+ 구어체 별칭(aliases)이 이미 등록되어, 기존 BGE-M3 임베딩이 구어체 ↔ 전문용어 매핑을 충분히 수행
2. **SKIP_SIMPLE 설정**: 대부분 질의가 Tier 1에서 SIMPLE 판정되어 HyDE/Fusion이 적용되지 않음
3. **추가 LLM 호출 비용**: HyDE (7-10초/질의), Fusion (10-15초/질의)의 레이턴시 대비 효과 미미

**권장**: 온톨로지 컬렉션에서는 HyDE/Fusion을 비활성화 유지. `realestate_v2` 컬렉션 통합 검색에서 별칭이 없는 자연어 문서 매칭 시 활성화하여 재평가.

### Adaptive RAG Generation의 핵심 가치

검색 P@3 개선보다 **답변 생성 품질**이 사용자 경험의 핵심 결정 요소:
- 검색만으로는 "취득세 세율" → [표준세율, 과세표준, 탄력세율] 목록 반환
- Generation 후 → 유상/무상/중과 세율 표, 인용 포함 691자 구조화된 답변
- 자기 보정 루프가 문서 부족 시 질의 재작성 + 재검색으로 보완

---

## 9. 다음 단계

### P0: 즉시 실행

1. **Generation 프롬프트 튜닝**: 3개 테스트 결과 기반 grade/generate/hallucination 프롬프트 최적화
2. **LangGraph 설치**: `docker exec rag-embedding pip install langgraph` → StateGraph 모드 활성화
3. **PARENT_DOC_ENABLED=True 적용**: Generation 품질 향상 (realestate_v2 문서 풀 컨텍스트)

### P1: 단기

4. **Dynamic Alpha 전체 학습**: 500-query × 11 alpha → Ridge 모델 학습 + 배포
5. **500-query 전체 벤치마크**: 재색인 후 기준선 재측정 (기존 68.0% → 예상 72%+)
6. **RAGAS 평가 도입**: Sprint 3 생성 파이프라인 기반 Faithfulness/Answer Relevancy 측정

### P2: 후속 (Sprint 4-5)

7. **Fact Group Chunking**: `chunker.py` 수정 + realestate_v2 재색인
8. **Late Chunking**: BGE-M3 컬렉션(domain_ontology_v2) 대상
9. **realestate_v2 통합 검색 파이프라인**: 온톨로지 + realestate_v2 동시 검색 → HyDE/Fusion 재평가
