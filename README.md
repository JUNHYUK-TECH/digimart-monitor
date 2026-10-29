# Digimart Monitor

GitHub Actions에서 매시간 Digimart 신규 매물을 확인합니다.

조건:
- Tyler / Gibson / PRS / Fender / Nord / Helix / Quad Cortex / Fractal
- 100,000엔 초과, 1,000,000엔 미만
- 키워드별 최신 검색결과를 여러 페이지 순회해 최대 300개 후보까지 확인
- Fender는 USA/American/Custom Shop 계열 중심, Arai Kazuki 예외
- Gibson은 Epiphone/Orville 제외
- 케이스/가방 등 액세서리 자체는 제외하되, "하드케이스 포함"처럼 정상 악기 제목에 액세서리 문구가 들어간 경우는 유지
- 첫 실행은 기준점만 저장하고 알림하지 않음
- 이후 신규 매물이 있으면 GitHub Issue 생성
- 동일 DS 상품 ID는 data/seen.json으로 중복 알림 방지

Actions 탭에서 Digimart Free Monitor → Run workflow로 수동 실행할 수 있습니다.

## 접근 차단 진단

- HTTP 403 또는 Cloudflare 챌린지를 감지하면 나머지 검색을 즉시 중단합니다.
- 실패 시 기존 seen.json을 보존하고 latest.json에 실패 원인을 기록합니다.
  실패 상태의 new: []는 신규 매물이 없다는 의미가 아닙니다.
- last_attempt_at과 last_success_at을 분리합니다. 이전 성공 시각을 알 수 없으면 null입니다.
- 로그에는 응답 상태와 제한된 진단 헤더만 남기며 Cloudflare URL 토큰을 제거합니다.
- 수동 실행은 diagnostic=true가 기본값입니다. 첫 키워드의 한 페이지만 확인하며
  상태 파일과 Issue를 변경하지 않습니다. 정상 수집은 diagnostic=false로 실행합니다.
- 로컬 진단: python monitor.py --diagnostic
- 오프라인 검증: python -m unittest discover -s tests -v
- 이 변경은 차단을 해제하거나 우회하지 않습니다. 403이 계속되면 반복 재시도보다
  응답 진단과 Digimart가 허용하는 수집 방식 확인이 필요합니다.

