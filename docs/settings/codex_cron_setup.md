# ChatGPT Codex CLI Cron Job 환경 설정

> 점검일: 2026-03-08

## 1. 환경 상태

| 항목 | 상태 | 상세 |
|------|------|------|
| Codex CLI | v0.111.0 (글로벌) | `~/.nvm/versions/node/v24.14.0/bin/codex` |
| Node.js | v24.14.0 (LTS) | Gemini와 공유 |
| 인증 방식 | chatgpt (OAuth) | `~/.codex/auth.json` — access_token + refresh_token |
| 모델 | gpt-5.2 | `~/.codex/config.toml` |

## 2. Codex CLI 비대화형 모드

`codex exec` 서브커맨드로 headless 실행:

```bash
codex exec "프롬프트 내용"              # 인자로 전달
echo "프롬프트" | codex exec -          # stdin으로 전달

# 주요 옵션
-m, --model <MODEL>                     # 모델 지정
-o, --output-last-message <FILE>        # 결과를 파일로 저장
--skip-git-repo-check                   # git repo 밖에서도 실행
--ephemeral                             # 세션 파일 미저장
--dangerously-bypass-approvals-and-sandbox  # 자동 승인 (YOLO)
-C, --cd <DIR>                          # 작업 디렉토리 지정
```

## 3. 파일 구조

```
codes/cron/
├── config/
│   ├── gemini_tasks.yaml      # Gemini 작업 설정
│   └── codex_tasks.yaml       # Codex 작업 설정
├── logs/
├── gemini_preprocess.sh       # Gemini 실행 스크립트
├── codex_preprocess.sh        # Codex 실행 스크립트
└── manage_cron.sh             # crontab 관리 (Gemini + Codex 통합)
```

## 4. 주의사항

- Codex도 OAuth(chatgpt) 인증이므로 headless 토큰 갱신 테스트 필요
- `--dangerously-bypass-approvals-and-sandbox` 사용 시 파일 쓰기 권한 완전 개방
- Gemini와 동일한 nvm 환경 사용, 래퍼 스크립트에서 nvm source 필수
