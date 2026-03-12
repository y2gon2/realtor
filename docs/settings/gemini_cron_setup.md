# Gemini CLI Cron Job 환경 설정

> 점검일: 2026-03-08

## 1. 환경 상태

| 항목 | 상태 | 상세 |
|------|------|------|
| Node.js | v24.14.0 (LTS Krypton) | nvm 경유, `~/.nvm/versions/node/v24.14.0/` |
| nvm | 설치됨 | `~/.nvm/` |
| Gemini CLI | v0.32.1 (글로벌) | `~/.nvm/versions/node/v24.14.0/bin/gemini` |
| OAuth 인증 | 정상 | `y2gon3@gmail.com`, refresh_token 있음 |
| 인증 방식 | oauth-personal | `~/.gemini/settings.json` |
| Cron 서비스 | active | `systemctl is-active cron` |
| PyYAML | 설치됨 | `/usr/lib/python3/dist-packages/` (시스템 패키지) |

## 2. 파일 구조

```
codes/cron/
├── config/
│   └── gemini_tasks.yaml      # 스케줄, 프롬프트, 참고문서, 모델 등 설정
├── logs/                       # 실행 로그 (task별 날짜별)
├── gemini_preprocess.sh        # 메인 실행 스크립트
└── manage_cron.sh              # crontab 등록/해제/상태 관리
```

## 3. 설정 파일 (gemini_tasks.yaml) 구조

```yaml
global:                          # 공통 설정
  project_root: "/home/gon/ws/rag"
  gemini_bin: "..."
  default_model: "gemini-2.5-flash"
  batch_size: 3                  # 1회 실행 시 처리 파일 수

tasks:
  task_name:                     # 각 task 독립 설정
    enabled: true/false          # 개별 활성화/비활성화
    schedule: "0 */2 * * *"      # cron 스케줄 (여기서 변경)
    prompt_file: "경로/prompt.md" # 프롬프트 파일 (변경 가능)
    reference_docs:               # 참고 문서 목록 (추가/변경 가능)
      - "경로/ref1.md"
    source_dir: "입력폴더"
    output_dir: "출력폴더"
    model: "모델 오버라이드"      # 생략 시 global.default_model
```

## 4. 사용법

```bash
# task 목록 및 상태 확인
./codes/cron/gemini_preprocess.sh

# 수동 실행 (테스트)
./codes/cron/gemini_preprocess.sh v2_refine_from_done

# crontab 등록 (yaml의 schedule 기반)
./codes/cron/manage_cron.sh install

# crontab 상태 확인
./codes/cron/manage_cron.sh status

# crontab 제거
./codes/cron/manage_cron.sh remove
```

## 5. 변경 시나리오

| 변경 사항 | 수정 대상 |
|-----------|-----------|
| 실행 주기 변경 | `config/gemini_tasks.yaml` → `tasks.xxx.schedule` 수정 후 `manage_cron.sh install` |
| 프롬프트 내용 변경 | `llm_task/rag_prepare/` 내 해당 md 파일 직접 수정 |
| 프롬프트 파일 교체 | `config/gemini_tasks.yaml` → `tasks.xxx.prompt_file` 경로 변경 |
| 참고 문서 추가/변경 | `config/gemini_tasks.yaml` → `tasks.xxx.reference_docs` 목록 수정 |
| 모델 변경 | `config/gemini_tasks.yaml` → `global.default_model` 또는 `tasks.xxx.model` |
| 배치 크기 변경 | `config/gemini_tasks.yaml` → `global.batch_size` |
| task 비활성화 | `config/gemini_tasks.yaml` → `tasks.xxx.enabled: false` |

## 6. Gemini CLI 비대화형 옵션 레퍼런스

```
-p, --prompt        비대화형(headless) 모드. 프롬프트 문자열 전달
-m, --model         모델 지정
-y, --yolo          모든 도구 사용 자동 승인
--approval-mode     default | auto_edit | yolo | plan
-o, --output-format text | json | stream-json
-s, --sandbox       샌드박스 모드
```

## 7. 주의사항

- Cron 환경에서 nvm 로드: 스크립트 내에서 `source $NVM_DIR/nvm.sh` 처리됨
- 동일 task 중복 실행 방지: lock 파일 메커니즘 내장 (`/tmp/gemini_cron_locks/`)
- OAuth 토큰: `refresh_token` 기반 자동 갱신 예상, headless 테스트 필요
- 토큰 실패 시: `GEMINI_API_KEY` 환경변수 방식으로 전환 가능

## 8. 다음 단계

- [ ] headless 환경에서 실제 Gemini CLI 실행 테스트 (`gemini -p "test" -o text`)
- [ ] OAuth 토큰 갱신 정상 동작 확인
- [ ] 실제 파일 1개로 전처리 end-to-end 테스트
- [ ] crontab 등록 (`manage_cron.sh install`)
