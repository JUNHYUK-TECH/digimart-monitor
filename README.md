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
