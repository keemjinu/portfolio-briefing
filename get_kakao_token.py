"""
카카오 Refresh Token 발급 (최초 1회만 실행)
발급받은 refresh_token을 GitHub Secret에 KAKAO_REFRESH_TOKEN으로 저장하세요.

사전 준비:
  1. https://developers.kakao.com 로그인
  2. 내 애플리케이션 → 앱 선택 (또는 새로 생성)
  3. 앱 설정 → 카카오 로그인 → 활성화
  4. 제품 설정 → 카카오 로그인 → Redirect URI 추가: https://localhost
  5. 동의항목 → '카카오톡 메시지 전송' 동의 설정
  6. 앱 키 → REST API 키 복사 → 아래 REST_API_KEY에 입력
"""

import urllib.parse, urllib.request, json

REST_API_KEY = input("Kakao REST API 키를 입력하세요: ").strip()

# Step 1: 인증 URL 열기
auth_url = (
    f"https://kauth.kakao.com/oauth/authorize"
    f"?client_id={REST_API_KEY}"
    f"&redirect_uri=https://localhost"
    f"&response_type=code"
    f"&scope=talk_message"
)
print(f"\n아래 URL을 브라우저에서 열고 로그인 후 리다이렉트된 URL을 복사하세요:\n")
print(auth_url)
print()

# Step 2: 리다이렉트 URL에서 code 추출
redirect_url = input("리다이렉트된 전체 URL을 붙여넣으세요: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query).get("code", [None])[0]
if not code:
    print("❌ code를 찾을 수 없습니다. URL을 다시 확인하세요.")
    exit(1)

# Step 3: 토큰 발급
data = urllib.parse.urlencode({
    "grant_type":   "authorization_code",
    "client_id":    REST_API_KEY,
    "redirect_uri": "https://localhost",
    "code":         code,
}).encode()

req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data)
with urllib.request.urlopen(req) as res:
    tokens = json.loads(res.read().decode())

print("\n✅ 토큰 발급 완료!")
print(f"\n아래 값을 GitHub Secret에 추가하세요:")
print(f"  KAKAO_REST_API_KEY  = {REST_API_KEY}")
print(f"  KAKAO_REFRESH_TOKEN = {tokens.get('refresh_token')}")
print(f"\n(access_token 유효기간: 6시간 / refresh_token 유효기간: 60일)")
print("refresh_token이 만료되면 이 스크립트를 다시 실행하세요.")
