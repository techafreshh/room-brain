# RoomBrain agent image (VPS deployment behind the techa.pro gateway).
#
# Runtime deps only: the run path uses httpx (ops + capture), websockets
# (Switch WS client), and pydantic (frame models). fastembed and sqlite-vec
# stay opt-in extras (ROOMBRAIN_NO_EMBED=1 is the code default) and are
# excluded to keep the image small; the openai package backs llm/client.py,
# which nothing on the run path imports.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir "httpx" "websockets>=15" "pydantic>=2"
COPY . .

CMD ["python", "-m", "roombrain", "run"]
