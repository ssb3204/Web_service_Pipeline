FROM python:3.14-slim

WORKDIR /app

# Python zoneinfo가 'Asia/Seoul'을 해석하려면 OS tzdata 또는 환경변수가 필요.
# requirements.txt에도 tzdata가 있어 Python 패키지로도 보강됨.
ENV TZ=Asia/Seoul

# 의존성 먼저 복사·설치 → 코드 변경 시 의존성 레이어 캐시 재사용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 실제 실행 코드 복사
COPY event_generator.py .

CMD ["python", "event_generator.py"]
